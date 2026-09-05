"""Materialize and validate the source-backed CodeQL analysis plan."""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
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
    """Report an invalid source plan or failed validation command."""


def _run(command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> None:
    """Run one validation command and report its captured failure."""
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    detail = completed.stdout + completed.stderr
    raise PlanError(f"command failed: {' '.join(command)}\n{detail}")


def _relative(value: str) -> Path:
    """Require one normalized repository-relative path."""
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise PlanError(f"invalid plan path: {value}")
    return path


def _selected_blocks(
    plan: dict[str, Any],
    requested: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Return each requested block after its dependencies, once."""
    blocks = {block["id"]: block for block in plan["blocks"]}
    missing = sorted(set(requested) - blocks.keys())
    if missing:
        raise PlanError(f"unknown blocks: {missing}")

    selected: list[dict[str, Any]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def add(block_id: str) -> None:
        if block_id in visited:
            return
        if block_id in visiting:
            raise PlanError(f"block dependency cycle at {block_id}")
        visiting.add(block_id)
        block = blocks[block_id]
        for dependency in block["depends_on"]:
            if dependency not in blocks:
                raise PlanError(f"unknown dependency: {dependency}")
            add(dependency)
        visiting.remove(block_id)
        visited.add(block_id)
        selected.append(block)

    for block_id in requested:
        add(block_id)
    return tuple(selected)


def _patch_paths(file: dict[str, Any]) -> tuple[Path, ...]:
    """Validate the paths that one patch is allowed to change."""
    values = file.get("destinations")
    if not isinstance(values, list) or not values:
        raise PlanError("patch action requires destinations")
    return tuple(_relative(value) for value in values)


def _applied_patch_paths(source: Path, output: Path) -> tuple[Path, ...]:
    """Read the paths Git will change before applying a reviewed patch."""
    completed = subprocess.run(
        ("git", "apply", "--numstat", str(source)),
        cwd=output,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PlanError(f"cannot inspect patch: {source}\n{completed.stderr}")
    paths: list[Path] = []
    for line in completed.stdout.splitlines():
        columns = line.split("\t")
        if len(columns) != 3:
            raise PlanError(f"invalid patch summary: {line}")
        paths.append(_relative(columns[2]))
    return tuple(paths)


def _materialize(
    output: Path,
    plan: dict[str, Any],
    blocks: Sequence[dict[str, Any]],
) -> tuple[Path, ...]:
    """Extract the baseline and apply the selected blocks in dependency order."""
    if output.exists():
        raise PlanError(f"output already exists: {output}")
    archive = subprocess.run(
        ("git", "archive", str(plan["baseline"])),
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    output.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(output, filter="data")

    changed: list[Path] = []
    for block in blocks:
        for file in block["files"]:
            action = file["action"]
            if action == "patch":
                source = PLAN_ROOT / _relative(file["source"])
                if not source.is_file():
                    raise PlanError(f"plan source is absent: {file['source']}")
                paths = _patch_paths(file)
                actual = _applied_patch_paths(source, output)
                if set(actual) != set(paths) or len(actual) != len(paths):
                    raise PlanError(
                        f"patch destinations differ: {file['source']}"
                    )
                completed = subprocess.run(
                    ("git", "apply", "--whitespace=error", str(source)),
                    cwd=output,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    raise PlanError(
                        f"patch failed: {file['source']}\n{completed.stderr}"
                    )
                changed.extend(path for path in paths if path.suffix == ".py")
                continue

            destination = output / _relative(file["destination"])
            if action == "remove":
                if not destination.is_file():
                    raise PlanError(f"remove target is absent: {file['destination']}")
                destination.unlink()
                continue

            source = PLAN_ROOT / _relative(file["source"])
            if not source.is_file():
                raise PlanError(f"plan source is absent: {file['source']}")
            if action == "add" and destination.exists():
                raise PlanError(f"add target already exists: {file['destination']}")
            if action == "replace" and not destination.is_file():
                raise PlanError(f"replace target is absent: {file['destination']}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if destination.suffix == ".py":
                changed.append(destination.relative_to(output))
    return tuple(dict.fromkeys(changed))


def _validate(
    output: Path,
    changed: tuple[Path, ...],
    blocks: Sequence[dict[str, Any]],
) -> None:
    """Run the plan's static checks and focused tests without changing its files."""
    tools = ROOT / ".venv/bin"
    python = tools / "python"
    ruff = tools / "ruff"
    pyright = tools / "pyright"
    for executable in (python, ruff, pyright):
        if not executable.is_file():
            raise PlanError(f"required project tool is absent: {executable}")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(output / "src"), str(output)))
    env["PATH"] = os.pathsep.join((str(tools), env["PATH"]))
    files = tuple(str(path) for path in changed)
    _run((str(ruff), "check", *files), cwd=output, env=env)
    _run((str(ruff), "format", "--check", *files), cwd=output, env=env)
    _run((str(pyright), *files, "--pythonpath", str(python)), cwd=output, env=env)
    selected = {block["id"] for block in blocks}
    tests = ["tests/test_codeql_graph_semantics.py"]
    if "P0-CQA-02" in selected:
        tests.extend(("tests/test_codeql_analysis.py", "tests/test_system_impact.py"))
    else:
        env["VIPER_RUN_CODEQL_TESTS"] = "1"
    _run(
        (
            str(python),
            "-m",
            "pytest",
            *tests,
            "-q",
        ),
        cwd=output,
        env=env,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Materialize the reviewed plan and run its focused gate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", action="append", dest="blocks")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    plan = tomllib.loads(PLAN.read_text(encoding="utf-8"))
    requested = args.blocks or [plan["blocks"][-1]["id"]]
    blocks = _selected_blocks(plan, requested)
    output = (
        args.output.resolve()
        if args.output is not None
        else Path(tempfile.mkdtemp(prefix="viper-codeql-analysis.")) / "candidate"
    )
    changed = _materialize(output, plan, blocks)
    _validate(output, changed, blocks)
    print(f"source plan passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
