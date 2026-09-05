"""Materialize and validate the source-backed rename-obligation plan."""

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
import textwrap
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
PLAN_ROOT = Path(__file__).parent
PLAN = PLAN_ROOT / "plan.toml"
_GRAPH_CHECK = textwrap.dedent(
    """
    import json
    import sys
    from pathlib import Path

    from viper._system_impact.codeql import (
        analyze_source,
        resolve_analysis_specs,
        source_digest,
    )
    from viper.system_impact.models import SourceSnapshot

    baseline = Path(sys.argv[1]).resolve()
    candidate = Path(sys.argv[2]).resolve()
    codeql = Path(sys.argv[3]).resolve()
    cache = Path(sys.argv[4]).resolve()
    artifacts = Path(sys.argv[5]).resolve()
    revision = sys.argv[6]
    pack = candidate / "tools/codeql/viper-python-impact"
    extraction, query, format_spec = resolve_analysis_specs(
        candidate,
        codeql_executable=codeql,
        query_pack=pack,
    )

    def analyze(root, *, committed, label):
        snapshot = SourceSnapshot(
            base_revision=revision,
            source_sha256=source_digest(root),
            revision=revision if committed else None,
        )
        return analyze_source(
            root,
            snapshot=snapshot,
            extraction=extraction,
            query=query,
            format=format_spec,
            codeql_executable=codeql,
            query_pack=pack,
            cache_root=cache,
            artifact_root=artifacts / label,
        )

    before = analyze(baseline, committed=True, label="baseline")
    after = analyze(candidate, committed=False, label="candidate")
    expected = {
        "src/viper/system_impact/rename.py:compile_rename_obligations",
        "src/viper/system_impact/rename.py:check_rename_obligations",
        "src/viper/system_impact/rename.py:render_rename_check",
    }
    nodes = {node.node_id for node in after.nodes}
    absent = sorted(expected - nodes)
    incoming = {
        edge.target
        for edge in after.edges
        if edge.target in expected and edge.source.startswith("tests/")
    }
    unobserved = sorted(expected - incoming)
    if absent or unobserved:
        raise SystemExit(
            "planned-source graph closure failed: "
            + json.dumps({"absent": absent, "unobserved": unobserved})
        )
    print(
        json.dumps(
            {
                "baseline_graph": before.receipt.graph.sha256,
                "candidate_graph": after.receipt.graph.sha256,
                "extraction": extraction.model_dump(mode="json"),
                "query": query.model_dump(mode="json"),
                "format": format_spec.model_dump(mode="json"),
                "observed_targets": sorted(incoming),
            },
            sort_keys=True,
        )
    )
    """
)


class PlanError(RuntimeError):
    """Report an invalid plan or failed validation command."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 900.0,
) -> subprocess.CompletedProcess[str]:
    """Run one command and preserve its output for failure diagnosis."""
    try:
        completed = subprocess.run(
            tuple(command),
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise PlanError(f"command timed out: {' '.join(command)}") from error
    if completed.returncode != 0:
        detail = completed.stdout + completed.stderr
        raise PlanError(f"command failed: {' '.join(command)}\n{detail}")
    return completed


def _relative(value: str) -> Path:
    """Require one normalized repository-relative path."""
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise PlanError(f"invalid plan path: {value}")
    return path


def _load_plan() -> dict[str, Any]:
    """Load and minimally validate the source-plan manifest."""
    plan = tomllib.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1:
        raise PlanError("plan schema_version must equal 1")
    blocks = plan.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != 1:
        raise PlanError("plan must contain exactly one PairBlock")
    if blocks[0].get("id") != "P0-ROC-01":
        raise PlanError("plan must own P0-ROC-01")
    return plan


def _extract_revision(revision: str, output: Path) -> None:
    """Extract one committed repository tree without changing a worktree."""
    archive = subprocess.run(
        ("git", "archive", revision),
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    output.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(output, filter="data")


def _materialize(plan: dict[str, Any], output: Path) -> tuple[Path, ...]:
    """Apply every declared file action to the isolated baseline."""
    block = plan["blocks"][0]
    changed: list[Path] = []
    for file in block["files"]:
        if file.get("action") == "patch":
            source = PLAN_ROOT / _relative(file["source"])
            declared = tuple(_relative(value) for value in file["destinations"])
            if not source.is_file():
                raise PlanError(f"plan source is absent: {file['source']}")
            inspected = subprocess.run(
                ("git", "apply", "--numstat", str(source)),
                cwd=output,
                check=False,
                capture_output=True,
                text=True,
            )
            actual = tuple(
                _relative(line.split("\t", 2)[2])
                for line in inspected.stdout.splitlines()
                if len(line.split("\t", 2)) == 3
            )
            if inspected.returncode != 0 or actual != declared:
                raise PlanError(f"patch destinations differ: {file['source']}")
            applied = subprocess.run(
                ("git", "apply", "--whitespace=error", str(source)),
                cwd=output,
                check=False,
                capture_output=True,
                text=True,
            )
            if applied.returncode != 0:
                raise PlanError(f"patch failed: {file['source']}\n{applied.stderr}")
            changed.extend(declared)
            continue
        if file.get("action") != "add":
            raise PlanError("rename-obligation plan accepts add and patch actions")
        source = PLAN_ROOT / _relative(file["source"])
        destination_relative = _relative(file["destination"])
        destination = output / destination_relative
        if not source.is_file():
            raise PlanError(f"plan source is absent: {file['source']}")
        if destination.exists():
            raise PlanError(f"add target already exists: {file['destination']}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        changed.append(destination_relative)
    return tuple(changed)


def _repository_status() -> str:
    """Return the active worktree's exact short status."""
    return subprocess.run(
        ("git", "status", "--short"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _validate(
    *,
    baseline: Path,
    candidate: Path,
    changed: tuple[Path, ...],
    revision: str,
    results: Path,
) -> dict[str, Any]:
    """Run static, focused, and same-identity source-graph gates."""
    python = Path(sys.executable)
    tools = python.parent
    ruff = tools / "ruff"
    pyright = tools / "pyright"
    for executable in (python, ruff, pyright):
        if not executable.is_file():
            raise PlanError(f"required project tool is absent: {executable}")
    codeql_command = shutil.which("codeql")
    if codeql_command is None:
        raise PlanError("CodeQL executable is absent from PATH")
    codeql = Path(codeql_command).resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(candidate / "src"), str(candidate)))
    env["PATH"] = os.pathsep.join((str(tools), env["PATH"]))
    files = tuple(str(path) for path in changed)
    commands = (
        (str(ruff), "check", *files),
        (str(ruff), "format", "--check", *files),
        (
            str(pyright),
            *files,
            "--venvpath",
            str(python.parents[2]),
        ),
        (
            str(python),
            "-m",
            "pytest",
            "tests/test_rename_obligations.py",
            "-q",
        ),
    )
    outcomes: list[dict[str, object]] = []
    for command in commands:
        completed = _run(command, cwd=candidate, env=env)
        outcomes.append(
            {
                "command": list(command),
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    graph = _run(
        (
            str(python),
            "-c",
            _GRAPH_CHECK,
            str(baseline),
            str(candidate),
            str(codeql),
            str(results / "cache"),
            str(results / "artifacts"),
            revision,
        ),
        cwd=candidate,
        env=env,
        timeout=1800.0,
    )
    return {"commands": outcomes, "graph": json.loads(graph.stdout)}


def main(argv: Sequence[str] | None = None) -> int:
    """Materialize the reviewed block and run its complete gate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    plan = _load_plan()
    revision = str(plan["baseline"])
    before_status = _repository_status()
    results = (
        arguments.output.resolve()
        if arguments.output is not None
        else Path(tempfile.mkdtemp(prefix="viper-rename-obligation."))
    )
    if results.exists() and any(results.iterdir()):
        raise PlanError(f"output directory is not empty: {results}")
    results.mkdir(parents=True, exist_ok=True)
    baseline = results / "baseline"
    candidate = results / "candidate"
    _extract_revision(revision, baseline)
    _extract_revision(revision, candidate)
    changed = _materialize(plan, candidate)
    evidence = _validate(
        baseline=baseline,
        candidate=candidate,
        changed=changed,
        revision=revision,
        results=results,
    )
    after_status = _repository_status()
    if after_status != before_status:
        raise PlanError("source-plan validation changed the active working tree")
    evidence_path = results / "result.json"
    evidence_path.write_text(
        json.dumps(
            {
                "block": "P0-ROC-01",
                "candidate": str(candidate),
                "changed": [str(path) for path in changed],
                **evidence,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"source plan passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
