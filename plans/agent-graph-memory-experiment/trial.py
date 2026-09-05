"""Execute one coding-agent arm as a VIPER build stage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from viper.metrics import MetricContext, metric
from viper.params import Train
from viper.stages import Context, train

Arm = Literal["ordinary", "static_graph", "graph_predicate"]


class AgentTrialParameters(Train):
    """Select one treatment and its externally enforced agent controls."""

    arm: Arm
    model: str = Field(min_length=1)
    timeout_seconds: int = Field(gt=0)
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def load_bytes(path: Path) -> bytes:
    """Load one experiment artifact without changing its representation."""
    return path.read_bytes()


@metric(metric_id="candidate_acceptance", mode="live")
def candidate_acceptance(
    context: MetricContext,
    accepted: float,
) -> float:
    """Return the hidden evaluator's binary acceptance observation."""
    del context
    return accepted


def _extract_tar(path: Path, destination: Path) -> None:
    """Extract regular files and directories beneath one destination."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("archive member escapes its destination")
            if not (member.isdir() or member.isfile()):
                raise ValueError("archive contains a non-regular member")
        archive.extractall(destination, filter="data")


def _require_digest(path: Path, expected: str) -> None:
    """Reject an input whose delivered bytes differ from the frozen plan."""
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"input digest differs: {path.name}")


def _usage(transcript: Path) -> dict[str, int]:
    """Extract counters observable in the Codex JSONL stream."""
    token_usage: dict[str, int] = {}
    commands: list[str] = []
    agent_messages = 0
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(
            event.get("usage"), dict
        ):
            token_usage = event["usage"]
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if item.get("type") == "agent_message":
            agent_messages += 1
        if item.get("type") == "command_execution" and isinstance(
            item.get("command"), str
        ):
            commands.append(item["command"])
    search_markers = ("rg ", "rg --files", "grep ", "find ")
    searches = sum(
        any(marker in command for marker in search_markers) for command in commands
    )
    return {
        "input_tokens": token_usage.get("input_tokens", 0),
        "cached_input_tokens": token_usage.get("cached_input_tokens", 0),
        "output_tokens": token_usage.get("output_tokens", 0),
        "reasoning_tokens": token_usage.get("reasoning_output_tokens", 0),
        "agent_messages": agent_messages,
        "commands": len(commands),
        "repository_searches": searches,
        "predicate_calls": sum(".viper/unresolved.py" in item for item in commands),
    }


def _run_agent(
    candidate: Path,
    *,
    prompt: str,
    model: str,
    timeout_seconds: int,
    transcript: Path,
) -> tuple[float, bool, int | None]:
    """Launch one agent and enforce a deadline absent from its prompt."""
    command = (
        "codex",
        "exec",
        "--json",
        "--model",
        model,
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "--cd",
        str(candidate),
        prompt,
    )
    started = time.monotonic()
    with transcript.open("wb") as stream:
        process = subprocess.Popen(
            command,
            cwd=candidate,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            exit_code = None
    return time.monotonic() - started, timed_out, exit_code


def _candidate_archive(candidate: Path, output: Path) -> None:
    """Archive the complete candidate except Git and predicate caches."""
    with tarfile.open(output, "w:gz") as archive:
        for path in sorted(candidate.rglob("*")):
            relative = path.relative_to(candidate)
            if ".git" in relative.parts or ".viper" in relative.parts:
                continue
            archive.add(path, arcname=relative.as_posix(), recursive=False)


def _candidate_digest(candidate: Path) -> str:
    """Hash every retained candidate file by relative path and content."""
    rows = []
    for path in sorted(item for item in candidate.rglob("*") if item.is_file()):
        relative = path.relative_to(candidate)
        if (
            ".git" in relative.parts
            or ".viper" in relative.parts
            or "__pycache__" in relative.parts
            or path.suffix == ".pyc"
        ):
            continue
        rows.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@train(params=AgentTrialParameters)
def run_agent_trial(context: Context[AgentTrialParameters]) -> None:
    """Run one arm, evaluate it once, and write only declared artifacts."""
    outputs = context.artifacts
    _require_digest(context.inputs["fixture"], context.params.fixture_sha256)
    _require_digest(
        context.inputs["graph_evidence"],
        context.params.graph_evidence_sha256,
    )
    _require_digest(context.inputs["prompt"], context.params.prompt_sha256)
    _require_digest(context.inputs["evaluator"], context.params.evaluator_sha256)
    for path in outputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="viper-agent-trial-") as directory:
        workspace = Path(directory)
        candidate = workspace / "candidate"
        evidence = workspace / "evidence"
        _extract_tar(context.inputs["fixture"], candidate)
        _extract_tar(context.inputs["graph_evidence"], evidence)
        if context.params.arm in {"static_graph", "graph_predicate"}:
            shutil.copy2(
                evidence / "impact-relationships.json",
                candidate / "IMPACT_RELATIONSHIPS.json",
            )
        if context.params.arm == "graph_predicate":
            tool_root = candidate / ".viper"
            tool_root.mkdir()
            shutil.copy2(
                Path(__file__).with_name("predicate.py"),
                tool_root / "unresolved.py",
            )
            shutil.copytree(evidence, tool_root / "evidence")
        prompt = context.inputs["prompt"].read_text(encoding="utf-8")
        duration, timed_out, exit_code = _run_agent(
            candidate,
            prompt=prompt,
            model=context.params.model,
            timeout_seconds=context.params.timeout_seconds,
            transcript=outputs["transcript"],
        )
        patch = subprocess.run(
            ("git", "diff", "--binary", "HEAD"),
            cwd=candidate,
            check=True,
            capture_output=True,
        ).stdout
        outputs["patch"].write_bytes(patch)
        evaluated_candidate_sha256 = _candidate_digest(candidate)
        evaluator = subprocess.run(
            (
                os.fspath(Path(sys.executable)),
                os.fspath(context.inputs["evaluator"]),
                os.fspath(candidate),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        candidate_unchanged = _candidate_digest(candidate) == evaluated_candidate_sha256
        outputs["evaluator_output"].write_text(
            evaluator.stdout + evaluator.stderr,
            encoding="utf-8",
        )
        _candidate_archive(candidate, outputs["model"])
        candidate_archive_sha256 = hashlib.sha256(
            outputs["model"].read_bytes()
        ).hexdigest()
        usage = _usage(outputs["transcript"])
        outputs["usage"].write_text(
            json.dumps(usage, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        accepted = evaluator.returncode == 0 and candidate_unchanged
        verdict = {
            "schema_version": 1,
            "arm": context.params.arm,
            "agent_exit_code": exit_code,
            "timed_out": timed_out,
            "duration_seconds": duration,
            "evaluator_exit_code": evaluator.returncode,
            "evaluated_candidate_sha256": evaluated_candidate_sha256,
            "candidate_unchanged_by_evaluator": candidate_unchanged,
            "candidate_archive_sha256": candidate_archive_sha256,
            "accepted": accepted,
        }
        serialized_verdict = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
        outputs["verdict"].write_text(serialized_verdict, encoding="utf-8")
        outputs["state"].write_text(serialized_verdict, encoding="utf-8")
        context.metrics["candidate_acceptance"].record(float(accepted))


__all__ = [
    "AgentTrialParameters",
    "candidate_acceptance",
    "load_bytes",
    "run_agent_trial",
]
