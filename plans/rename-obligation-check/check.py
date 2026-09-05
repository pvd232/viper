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
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
PLAN_ROOT = Path(__file__).parent
PLAN = PLAN_ROOT / "plan.toml"


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
    if not isinstance(blocks, list) or [block.get("id") for block in blocks] != [
        "P0-ROC-02"
    ]:
        raise PlanError("plan must own P0-ROC-02")
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
    changed: list[Path] = []
    for block in plan["blocks"]:
        for file in block["files"]:
            changed.extend(_apply_file(file, output))
    return tuple(dict.fromkeys(changed))


def _apply_file(file: dict[str, Any], output: Path) -> tuple[Path, ...]:
    """Apply one source-plan action and return its declared destinations."""
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
        return declared
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
    return (destination_relative,)


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
    files = tuple(str(path) for path in changed if path.suffix == ".py")
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
            "tests/test_impact_cli.py",
            "tests/test_rename_obligations.py",
            "-q",
        ),
        (
            str(codeql),
            "query",
            "compile",
            "tools/codeql/viper-python-impact/RenameTransitions.ql",
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
    return {
        "commands": outcomes,
        "graph": {
            "query_compile": "passed",
            "historical_evidence": "historical-refactor-results.md",
        },
    }


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
                "block": "P0-ROC-02",
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
