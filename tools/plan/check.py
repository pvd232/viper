"""Check selected PairBlocks before editing source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

import viper.system_impact.models as impact
from viper import _subprocess as subprocess
from viper._contract_traceability import (
    ContractTarget,
    ContractTraceabilityGraph,
    PairBlockId,
    _implemented_pair_blocks,
    compile_contract_plan,
    compile_contract_traceability,
)
from viper._system_impact.codeql import (
    _tree_digest,
    analyze_source,
    lowering_digest,
    source_digest,
)
from viper._system_impact.source import (
    SourceDeclarationError,
    declaration_payload,
    extract_declaration_bytes,
    import_binding,
)
from viper.scheduling import (
    ScheduleError,
    materialize_plan,
    select_blocks,
)
from viper.system_impact.check import check_plan

ROOT = Path(__file__).parents[2]
_IMPORT_SCRIPT = (
    "import importlib\n"
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "importlib.import_module(sys.argv[2])\n"
)


class PlanValidationError(RuntimeError):
    """Report a failed pre-pairing plan check."""


@contextmanager
def _environment(**updates: str) -> Iterator[None]:
    """Restore process environment values after a scoped override."""
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one command without a shell."""
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed


def _git_revision(root: Path) -> str:
    """Return the current commit after requiring a clean checkout."""
    status = _run(("git", "status", "--porcelain"), cwd=root)
    if status.returncode != 0:
        raise PlanValidationError(status.stderr.strip() or "git status failed")
    if status.stdout:
        raise PlanValidationError("pre-pairing validation requires a clean baseline")
    revision = _run(("git", "rev-parse", "HEAD"), cwd=root)
    if revision.returncode != 0:
        raise PlanValidationError(revision.stderr.strip() or "git rev-parse failed")
    return revision.stdout.strip()


def _contracts(root: Path) -> tuple[Path, ...]:
    """Return the contracts in the baseline manifest."""
    manifest = json.loads(
        (root / "docs/development/contract-baselines.json").read_text()
    )
    return tuple(root / record["path"] for record in manifest["contracts"])


def _specs(
    executable: Path,
    query_pack: Path,
) -> tuple[
    impact.CodeQLExtractionSpec, impact.CodeQLQuerySpec, impact.SourceGraphFormat
]:
    """Identify extraction, queries, and graph conversion separately."""
    version = _run((str(executable), "version", "--format=json"), cwd=ROOT)
    if version.returncode != 0:
        raise PlanValidationError(version.stderr.strip() or "CodeQL version failed")
    languages = _run(
        (str(executable), "resolve", "languages", "--format=json"),
        cwd=ROOT,
    )
    if languages.returncode != 0:
        raise PlanValidationError(
            languages.stderr.strip() or "CodeQL language resolution failed"
        )
    candidates = json.loads(languages.stdout).get("python")
    if not isinstance(candidates, list) or not candidates:
        raise PlanValidationError("CodeQL has no Python extractor")
    pack = yaml.safe_load((query_pack / "qlpack.yml").read_text(encoding="utf-8"))
    if not isinstance(pack, dict):
        raise PlanValidationError("CodeQL pack metadata is not a mapping")
    return (
        impact.CodeQLExtractionSpec(
            version=json.loads(version.stdout)["version"],
            platform=f"{platform.system().lower()}-{platform.machine()}",
            executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            extractor_sha256=_tree_digest(Path(candidates[0]).resolve()),
        ),
        impact.CodeQLQuerySpec(
            pack=f"{pack['name']}@{pack['version']}",
            pack_sha256=_tree_digest(query_pack),
            suite="source-facts.qls",
        ),
        impact.SourceGraphFormat(
            schema_version=3,
            lowering_sha256=lowering_digest(),
        ),
    )


def _analyze(
    root: Path,
    *,
    revision: str,
    committed: bool,
    extraction: impact.CodeQLExtractionSpec,
    query: impact.CodeQLQuerySpec,
    format: impact.SourceGraphFormat,
    executable: Path,
    query_pack: Path,
    cache: Path,
    artifacts: Path,
) -> impact.SourceGraph:
    """Build a source graph and its receipt."""
    snapshot = impact.SourceSnapshot(
        base_revision=revision,
        source_sha256=source_digest(root),
        revision=revision if committed else None,
    )
    return analyze_source(
        root,
        snapshot=snapshot,
        extraction=extraction,
        query=query,
        format=format,
        codeql_executable=executable,
        query_pack=query_pack,
        cache_root=cache,
        artifact_root=artifacts,
    )


def _unconsumed_private_owners(
    traceability: ContractTraceabilityGraph,
    selected: frozenset[PairBlockId],
    graph: impact.SourceGraph,
) -> tuple[str, ...]:
    """Find new private owners that nothing uses."""
    targets = {
        (target.block_id, target.target): target
        for target in traceability.targets
        if target.block_id in selected
    }
    nodes = {(node.path, node.symbol): node for node in graph.nodes}
    incoming = {edge.target for edge in graph.edges}
    missing: list[str] = []
    for edge in traceability.edges:
        if edge.kind != "implementation" or edge.block_id not in selected:
            continue
        target = targets.get((edge.block_id, edge.target))
        if target is None or target.action != "add":
            continue
        if not edge.target.symbol.rsplit(".", maxsplit=1)[-1].startswith("_"):
            continue
        node = nodes.get((edge.target.path, edge.target.symbol))
        if node is not None and node.node_id not in incoming:
            missing.append(f"{edge.target.path}:{edge.target.symbol}")
    return tuple(sorted(missing))


def _changed_modules(root: Path, candidate: Path) -> tuple[str, ...]:
    """Return added or changed modules under the candidate package."""
    source_root = candidate / "src"
    modules: list[str] = []
    for path in sorted((source_root / "viper").rglob("*.py")):
        relative = path.relative_to(source_root)
        baseline = root / "src" / relative
        if baseline.is_file() and baseline.read_bytes() == path.read_bytes():
            continue
        parts = relative.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))
    return tuple(modules)


def _import_failure(
    root: Path,
    candidate: Path,
    python: Path,
    modules: tuple[str, ...],
) -> dict[str, Any] | None:
    """Return the first import failure introduced by the candidate."""
    for module in modules:
        baseline = _run(
            (
                str(python),
                "-I",
                "-c",
                _IMPORT_SCRIPT,
                str(root / "src"),
                module,
            ),
            cwd=root,
        )
        completed = _run(
            (
                str(python),
                "-I",
                "-c",
                _IMPORT_SCRIPT,
                str(candidate / "src"),
                module,
            ),
            cwd=candidate,
        )
        if completed.returncode == 0 or baseline.returncode != 0:
            continue
        return {
            "stage": "imports",
            "module": module,
            "error": completed.stderr.strip()
            or completed.stdout.strip()
            or f"failed to import {module}",
            "command": tuple(completed.args),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    return None


def _ruff(
    python: Path,
    targets: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Build Ruff checks that never rewrite the planned source."""
    return (
        (
            "ruff-format",
            (str(python), "-m", "ruff", "format", "--check", *targets),
        ),
        (
            "ruff-imports",
            (str(python), "-m", "ruff", "check", "--select", "I001", *targets),
        ),
        (
            "ruff",
            (str(python), "-m", "ruff", "check", "--ignore", "D100", *targets),
        ),
    )


def _format(
    python: Path,
    targets: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Build the two commands that format the final candidate copy."""
    return (
        (
            "ruff-format",
            (str(python), "-m", "ruff", "format", *targets),
        ),
        (
            "ruff-imports",
            (
                str(python),
                "-m",
                "ruff",
                "check",
                "--fix",
                "--select",
                "I001",
                *targets,
            ),
        ),
    )


def _parity(
    plan_root: Path,
    source_root: Path,
    targets: tuple[ContractTarget, ...],
    *,
    check_imports: bool = True,
) -> tuple[str, ...]:
    """Return targets that differ from the contract."""
    failures: list[str] = []
    for target in targets:
        path = source_root / target.target.path
        symbol = target.target.symbol
        expected = declaration_payload(plan_root, target)
        if (
            not check_imports
            and expected is not None
            and expected.startswith((b"import ", b"from "))
        ):
            continue
        try:
            actual = extract_declaration_bytes(path.read_bytes(), symbol)
        except (OSError, SyntaxError, SourceDeclarationError):
            actual = None
        if target.action == "remove":
            if actual is not None:
                failures.append(str(target.target))
            continue
        assert expected is not None
        if actual is None:
            failures.append(str(target.target))
        elif actual.startswith((b"import ", b"from ")):
            if import_binding(actual, symbol) != import_binding(expected, symbol):
                failures.append(str(target.target))
        elif actual != expected:
            failures.append(str(target.target))
    return tuple(sorted(failures))


def validate(
    *,
    root: Path,
    blocks: tuple[PairBlockId, ...],
    codeql: Path,
    python: Path,
    cache: Path,
    results: Path,
) -> dict[str, Any]:
    """Build the selected plan, check it, and save the result."""
    revision = _git_revision(root)
    contracts = _contracts(root)
    # Select blocks first; their requirements determine the full CTG.
    raw_blocks, raw_targets = compile_contract_plan(root, contracts)
    completed = _implemented_pair_blocks(
        root / "docs/development/master-execution-checklist.md"
    )
    plan = ContractTraceabilityGraph.model_construct(
        requirements=(),
        rules=(),
        edges=(),
        targets=raw_targets,
        blocks=raw_blocks,
    )
    selected = select_blocks(plan, blocks, completed=completed)
    if not selected:
        raise PlanValidationError("selected PairBlocks are already implemented")
    selected_ids = set(selected)
    requirement_ids = tuple(
        sorted(
            {
                requirement
                for block in raw_blocks
                if block.block_id in selected_ids
                for requirement in block.requirements
            }
        )
    )
    traceability = compile_contract_traceability(
        root,
        root / "docs/development/master-execution-checklist.md",
        contracts,
        requirement_ids=requirement_ids,
    )
    extraction, query, format = _specs(
        codeql,
        root / "tools/codeql/viper-python-impact",
    )
    results.mkdir(parents=True, exist_ok=False)
    # Every planned edit starts from the clean commit.
    baseline = _analyze(
        root,
        revision=revision,
        committed=True,
        extraction=extraction,
        query=query,
        format=format,
        executable=codeql,
        query_pack=root / "tools/codeql/viper-python-impact",
        cache=cache,
        artifacts=results / "baseline-codeql",
    )

    raw = results / "raw"
    try:
        materialize_plan(
            root,
            root,
            traceability,
            selected,
            baseline,
            raw,
            completed=completed,
        )
    except ScheduleError as error:
        result = {
            "passed": False,
            "stage": "materialize",
            "revision": revision,
            "blocks": selected,
            "error": str(error),
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result

    selected_targets = tuple(
        target for target in traceability.targets if target.block_id in selected_ids
    )
    raw_parity = _parity(root, raw, selected_targets, check_imports=False)
    if raw_parity:
        result = {
            "passed": False,
            "stage": "raw-parity",
            "revision": revision,
            "blocks": selected,
            "targets": raw_parity,
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result

    raw_modules = _changed_modules(root, raw)
    import_failure = _import_failure(root, raw, python, raw_modules)
    if import_failure is not None:
        result = {
            "passed": False,
            "revision": revision,
            "blocks": selected,
            "stage": "raw-imports",
            "error": import_failure,
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result

    python_targets = tuple(
        sorted(
            {
                str(target.target.path)
                for target in traceability.targets
                if target.block_id in selected_ids
                and Path(target.target.path).suffix in {".py", ".pyi"}
            }
        )
    )
    candidate = results / "candidate"
    shutil.copytree(raw, candidate)
    for stage, command in _format(python, python_targets):
        completed = _run(command, cwd=candidate)
        if completed.returncode != 0:
            result = {
                "passed": False,
                "stage": stage,
                "revision": revision,
                "blocks": selected,
                "command": tuple(completed.args),
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            (results / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n"
            )
            return result

    for stage, command in _ruff(python, python_targets):
        completed = _run(command, cwd=candidate)
        if completed.returncode != 0:
            result = {
                "passed": False,
                "stage": stage,
                "revision": revision,
                "blocks": selected,
                "command": tuple(completed.args),
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            (results / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n"
            )
            return result

    parity = _parity(root, candidate, selected_targets)
    if parity:
        result = {
            "passed": False,
            "stage": "parity",
            "revision": revision,
            "blocks": selected,
            "targets": parity,
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result

    modules = _changed_modules(root, candidate)
    import_failure = _import_failure(root, candidate, python, modules)
    if import_failure is not None:
        result = {
            "passed": False,
            "revision": revision,
            "blocks": selected,
            **import_failure,
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result

    # Gates run inside check_plan(), so keep the candidate importable until it ends.
    with _environment(PYTHONPATH=str(candidate / "src")):
        pyright = _run(
            (
                str(python),
                "-m",
                "pyright",
                str(candidate / "src"),
                "--project",
                str(candidate / "pyrightconfig.json"),
                "--pythonpath",
                str(python),
            ),
            cwd=candidate,
        )
        if pyright.returncode != 0:
            result = {
                "passed": False,
                "stage": "pyright",
                "revision": revision,
                "blocks": selected,
                "command": tuple(pyright.args),
                "stdout": pyright.stdout,
                "stderr": pyright.stderr,
            }
            (results / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n"
            )
            return result

        # CodeQL needs the candidate's Python; the gate inherits only PYTHONPATH.
        path = os.pathsep.join(
            part for part in (str(python.parent), os.environ.get("PATH")) if part
        )
        with _environment(PATH=path):
            planned = _analyze(
                candidate,
                revision=revision,
                committed=False,
                extraction=extraction,
                query=query,
                format=format,
                executable=codeql,
                query_pack=root / "tools/codeql/viper-python-impact",
                cache=cache,
                artifacts=results / "planned-codeql",
            )
        unconsumed = _unconsumed_private_owners(
            traceability,
            frozenset(selected),
            planned,
        )
        checked = check_plan(
            root=candidate,
            baseline_root=root,
            traceability=traceability,
            block_ids=selected,
            baseline=baseline,
            realized=planned,
        )
    result = {
        "passed": checked.passed and not unconsumed,
        "stage": "complete",
        "revision": revision,
        "blocks": selected,
        "raw_imports": raw_modules,
        "imports": modules,
        "pyright": {
            "command": tuple(pyright.args),
            "stdout": pyright.stdout,
            "stderr": pyright.stderr,
        },
        "unconsumed_private_owners": unconsumed,
        "check": checked.model_dump(mode="json"),
    }
    (results / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pre-pairing check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", action="append", required=True)
    codeql = shutil.which("codeql")
    parser.add_argument(
        "--codeql",
        type=Path,
        default=None if codeql is None else Path(codeql),
    )
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / ".viper/codeql-cache")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.codeql is None:
        parser.error("codeql is unavailable on PATH; install or expose CodeQL first")
    if args.java_home is not None:
        os.environ["CODEQL_JAVA_HOME"] = str(args.java_home.resolve())
    result = validate(
        root=args.root.resolve(),
        blocks=tuple(args.block),
        codeql=args.codeql.resolve(),
        python=Path(os.path.abspath(args.python)),
        cache=args.cache.resolve(),
        results=args.results.resolve(),
    )
    if result["passed"]:
        print(f"planned source passed: {', '.join(result['blocks'])}")
        return 0
    print(f"planned source failed during {result['stage']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
