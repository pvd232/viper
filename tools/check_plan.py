"""Check selected PairBlocks before editing source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The private CodeQL adapter imports the public models while loading.
import viper.system_impact as impact  # noqa: E402
from viper import _subprocess as subprocess  # noqa: E402
from viper._contract_traceability import (  # noqa: E402
    ContractTraceabilityGraph,
    PairBlockId,
    _implemented_pair_blocks,
    compile_contract_plan,
    compile_contract_traceability,
)
from viper._system_impact.codeql import (  # noqa: E402
    _tree_digest,
    analyze_source,
    source_digest,
)
from viper.scheduling import (  # noqa: E402
    ScheduleError,
    materialize_plan,
    select_blocks,
)


class PlanValidationError(RuntimeError):
    """Report a failed pre-pairing plan check."""


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


def _identity(executable: Path, query_pack: Path) -> impact.CodeQLIdentity:
    """Identify the CodeQL executable and query pack."""
    version = _run((str(executable), "version", "--format=json"), cwd=ROOT)
    if version.returncode != 0:
        raise PlanValidationError(version.stderr.strip() or "CodeQL version failed")
    payload = json.loads(version.stdout)
    pack_result = _run(
        (
            sys.executable,
            "-c",
            (
                "import json,yaml,pathlib; "
                "p=yaml.safe_load(pathlib.Path('qlpack.yml').read_text()); "
                "print(json.dumps(p))"
            ),
        ),
        cwd=query_pack,
    )
    if pack_result.returncode != 0:
        raise PlanValidationError(
            pack_result.stderr.strip() or "CodeQL pack inspection failed"
        )
    pack = json.loads(pack_result.stdout)
    return impact.CodeQLIdentity(
        version=payload["version"],
        platform=f"{platform.system().lower()}-{platform.machine()}",
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        pack=f"{pack['name']}@{pack['version']}",
        pack_sha256=_tree_digest(query_pack),
    )


def _analyze(
    root: Path,
    *,
    revision: str,
    committed: bool,
    identity: impact.CodeQLIdentity,
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
        identity=identity,
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
    identity = _identity(codeql, root / "tools/codeql/viper-python-impact")
    results.mkdir(parents=True, exist_ok=False)
    # Every planned edit starts from the clean commit.
    baseline = _analyze(
        root,
        revision=revision,
        committed=True,
        identity=identity,
        executable=codeql,
        query_pack=root / "tools/codeql/viper-python-impact",
        cache=cache,
        artifacts=results / "baseline-codeql",
    )

    candidate = results / "candidate"
    try:
        materialize_plan(
            root,
            root,
            traceability,
            selected,
            baseline,
            candidate,
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
    checks = (
        (
            "ruff-format",
            (str(python), "-m", "ruff", "format", *python_targets),
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
                *python_targets,
            ),
        ),
        (
            "ruff",
            (str(python), "-m", "ruff", "check", "--ignore", "D100", *python_targets),
        ),
    )
    for stage, command in checks:
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

    # Make Pyright import the candidate instead of the baseline.
    original_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(candidate / "src")
    pyright = _run(
        (
            str(python),
            "-m",
            "pyright",
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
        if original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = original_pythonpath
        return result

    # Pyright checks types first; CodeQL then observes G*.
    planned = _analyze(
        candidate,
        revision=revision,
        committed=False,
        identity=identity,
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
    checked = impact.check_plan(
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
    if original_pythonpath is None:
        os.environ.pop("PYTHONPATH", None)
    else:
        os.environ["PYTHONPATH"] = original_pythonpath
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
    args = parser.parse_args(argv)
    if args.codeql is None:
        parser.error("codeql is unavailable on PATH; install or expose CodeQL first")
    if args.java_home is not None:
        os.environ["CODEQL_JAVA_HOME"] = str(args.java_home.resolve())
    result = validate(
        root=ROOT,
        blocks=tuple(args.block),
        codeql=args.codeql.resolve(),
        python=args.python.resolve(),
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
