"""Materialize and validate the agent graph-memory experiment plan."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

from viper._system_impact.codeql import (
    analyze_source,
    resolve_analysis_specs,
    source_digest,
)
from viper.system_impact.models import SourceSnapshot

ROOT = Path(__file__).parents[2]
PLAN_ROOT = Path(__file__).parent
PLAN = PLAN_ROOT / "plan.toml"
BASELINE_REVISION = "9d2cdba7fc22fb29b9cf71fc6baef52e5a5935ca"


class PlanError(RuntimeError):
    """Report an invalid source plan or failed planned-source gate."""


def _run(command: tuple[str, ...], *, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if completed.returncode:
        raise PlanError(
            f"command failed: {' '.join(command)}\n{completed.stdout}{completed.stderr}"
        )


def _extract_revision(revision: str, destination: Path) -> None:
    raw = subprocess.run(
        ("git", "archive", revision),
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(destination, filter="data")


def _materialize(candidate: Path) -> tuple[Path, ...]:
    plan = tomllib.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1 or plan.get("baseline") != "9d2cdba":
        raise PlanError("plan identity or baseline is invalid")
    block = next(item for item in plan["blocks"] if item["id"] == "P0-AGM-01")
    changed = []
    for file in block["files"]:
        if file.get("action") != "add":
            raise PlanError("P0-AGM-01 accepts only add actions")
        source = PLAN_ROOT / file["source"]
        destination = candidate / file["destination"]
        if not source.is_file() or destination.exists():
            raise PlanError(f"invalid add action: {file['destination']}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        changed.append(Path(file["destination"]))
    return tuple(changed)


def _analyze(
    root: Path,
    revision: str | None,
    artifacts: Path,
    cache: Path,
):
    codeql_value = shutil.which("codeql")
    if codeql_value is None:
        raise PlanError("CodeQL is unavailable")
    codeql = Path(codeql_value).resolve()
    pack = ROOT / "tools/codeql/viper-python-impact"
    extraction, query, graph_format = resolve_analysis_specs(
        ROOT,
        codeql_executable=codeql,
        query_pack=pack,
        suite="source-facts.qls",
    )
    return analyze_source(
        root,
        snapshot=SourceSnapshot(
            base_revision=BASELINE_REVISION,
            source_sha256=source_digest(root),
            revision=revision,
        ),
        extraction=extraction,
        query=query,
        format=graph_format,
        codeql_executable=codeql,
        query_pack=pack,
        cache_root=cache,
        artifact_root=artifacts,
    )


def validate(output: Path) -> dict[str, object]:
    """Materialize the plan and run static, test, and source-graph gates."""
    status_before = subprocess.run(
        ("git", "status", "--short"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    baseline = output / "baseline"
    candidate = output / "candidate"
    _extract_revision(BASELINE_REVISION, baseline)
    _extract_revision(BASELINE_REVISION, candidate)
    changed = _materialize(candidate)
    python = Path(sys.executable)
    tools = python.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(candidate / "src"), str(candidate)))
    commands = (
        (str(tools / "ruff"), "check", *(str(path) for path in changed)),
        (str(tools / "ruff"), "format", "--check", *(str(path) for path in changed)),
        (str(tools / "pyright"), *(str(path) for path in changed)),
        (
            str(python),
            "-m",
            "pytest",
            "plans/agent-graph-memory-experiment/tests/test_experiment.py",
            "-q",
        ),
    )
    for command in commands:
        _run(command, cwd=candidate, env=env)
    cache = output / "codeql-cache"
    baseline_graph = _analyze(
        baseline,
        BASELINE_REVISION,
        output / "baseline-codeql",
        cache,
    )
    candidate_graph = _analyze(
        candidate,
        None,
        output / "candidate-codeql",
        cache,
    )
    if (
        baseline_graph.receipt.database.extraction
        != candidate_graph.receipt.database.extraction
        or baseline_graph.receipt.query.query != candidate_graph.receipt.query.query
        or baseline_graph.receipt.graph.format != candidate_graph.receipt.graph.format
    ):
        raise PlanError("baseline and candidate graphs use different identities")
    planned_paths = {str(path) for path in changed if path.suffix == ".py"}
    observed_paths = {str(node.path) for node in candidate_graph.nodes}
    missing = sorted(planned_paths - observed_paths)
    if missing:
        raise PlanError(f"planned Python files are absent from SourceGraph: {missing}")
    status_after = subprocess.run(
        ("git", "status", "--short"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status_after != status_before:
        raise PlanError("planned-source validation changed the active worktree")
    return {
        "passed": True,
        "block": "P0-AGM-01",
        "changed": [str(path) for path in changed],
        "baseline_graph_sha256": baseline_graph.receipt.graph.sha256,
        "candidate_graph_sha256": candidate_graph.receipt.graph.sha256,
        "commands": [list(command) for command in commands],
    }


def main() -> int:
    """Run the planned-source gate and retain its result."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    output = (
        arguments.output.resolve()
        if arguments.output
        else Path(tempfile.mkdtemp(prefix="viper-agent-graph-plan-"))
    )
    output.mkdir(parents=True, exist_ok=True)
    result = validate(output)
    (output / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output / "result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
