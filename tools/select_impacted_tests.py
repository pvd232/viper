"""Apply VIPER's test tiers and domains to portable graph-based selection."""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from source_impact import codeql, testing
from source_impact.models import SourceGraph, SourceNode

ANALYZED_SOURCE_ROOTS = frozenset({"src", "tests", "tools"})


class ImpactSelectionError(ValueError):
    """Report invalid graph evidence, observer ownership, or test selection."""


@dataclass(frozen=True, slots=True)
class DeclarationObserver:
    """Link one declaration to explicit tests and its fallback domain."""

    declaration: str
    tests: tuple[str, ...]
    fallback_domain: str


@dataclass(frozen=True, slots=True)
class ImpactManifest:
    """Hold VIPER's explicit observers and source-file fallback ownership."""

    observers: dict[str, DeclarationObserver]
    source_domains: dict[str, str]


def source_digest(
    root: Path,
    analyzed_roots: frozenset[str] = ANALYZED_SOURCE_ROOTS,
) -> str:
    """Apply VIPER's default scope to the shared source identity implementation."""
    return codeql.source_digest(root, analyzed_roots)


def load_source_graph(
    path: Path,
    source_root: Path,
    analyzed_roots: frozenset[str],
) -> SourceGraph:
    """Load the full current graph without dropping analysis limitations."""
    try:
        return codeql.load_source_graph(path, source_root, analyzed_roots)
    except (ValueError, OSError, RuntimeError) as error:
        raise ImpactSelectionError(str(error)) from error


def _pytest_module(reference: str) -> str:
    """Read one repository-relative pytest module, including nested directories."""
    path = reference.split("::", 1)[0]
    parts = PurePosixPath(path).parts
    filename = parts[-1] if parts else ""
    if (
        not parts
        or PurePosixPath(path).is_absolute()
        or parts[0] != "tests"
        or len(parts) < 2
        or ".." in parts
        or "\\" in path
        or not filename.endswith(".py")
        or not (filename.startswith("test_") or filename.endswith("_test.py"))
    ):
        raise ImpactSelectionError(f"invalid pytest module reference: {reference!r}")
    return path


def load_observers(path: Path) -> ImpactManifest:
    """Load unique explicit observers without imposing flat test directories."""
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ImpactSelectionError("observer manifest schema_version must equal 1")
    records = payload.get("declarations")
    if not isinstance(records, list) or not records:
        raise ImpactSelectionError("observer manifest needs declarations")

    observers: dict[str, DeclarationObserver] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ImpactSelectionError("declaration observer must be a table")
        declaration = record.get("id")
        tests = record.get("tests")
        domain = record.get("fallback_domain")
        if not isinstance(declaration, str) or ":" not in declaration:
            raise ImpactSelectionError("declaration observer needs a path:symbol id")
        if declaration in observers:
            raise ImpactSelectionError(f"duplicate declaration observer: {declaration}")
        if (
            not isinstance(tests, list)
            or not tests
            or not all(isinstance(test, str) and "::" in test for test in tests)
        ):
            raise ImpactSelectionError(f"invalid observing tests for {declaration}")
        for test in tests:
            _pytest_module(test)
        if not isinstance(domain, str) or not domain.startswith("domain_"):
            raise ImpactSelectionError(f"invalid fallback domain for {declaration}")
        observers[declaration] = DeclarationObserver(
            declaration=declaration,
            tests=tuple(tests),
            fallback_domain=domain,
        )
    raw_domains = payload.get("source_domains")
    if not isinstance(raw_domains, dict) or not raw_domains:
        raise ImpactSelectionError("observer manifest needs source_domains")
    source_domains: dict[str, str] = {}
    for source_path, domain in raw_domains.items():
        if (
            not isinstance(source_path, str)
            or not source_path.startswith("src/")
            or not source_path.endswith(".py")
            or not isinstance(domain, str)
            or not domain.startswith("domain_")
        ):
            raise ImpactSelectionError("invalid source-domain ownership")
        source_domains[source_path] = domain
    return ImpactManifest(observers=observers, source_domains=source_domains)


def _test_classification(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read VIPER's tier and domain maps without importing test configuration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments: dict[str, dict[str, str]] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {
            "TIER_BY_MODULE",
            "DOMAIN_BY_MODULE",
        }:
            continue
        value = ast.literal_eval(statement.value)
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.items()
        ):
            raise ImpactSelectionError(f"invalid pytest classification: {target.id}")
        assignments[target.id] = value
    try:
        tiers = assignments["TIER_BY_MODULE"]
        domains = assignments["DOMAIN_BY_MODULE"]
    except KeyError as error:
        raise ImpactSelectionError("pytest classification maps are missing") from error
    if tiers.keys() != domains.keys():
        raise ImpactSelectionError("test tier and domain ownership must agree")
    return tiers, domains


def _fallback_domain(
    declaration: str,
    nodes: Mapping[str, SourceNode],
    manifest: ImpactManifest,
    domains: Mapping[str, str],
) -> str:
    """Prefer a declaration's explicit fallback owner over file-level ownership."""
    node = nodes.get(declaration)
    symbolic = f"{node.path}:{node.symbol}" if node is not None else declaration
    observer = manifest.observers.get(declaration) or manifest.observers.get(symbolic)
    if observer is not None:
        return observer.fallback_domain
    source_path = node.path if node is not None else declaration.partition(":")[0]
    if PurePosixPath(source_path).parts[:1] == ("tests",):
        return domains.get(PurePosixPath(source_path).stem, "all")
    return manifest.source_domains.get(source_path, "all")


def _fallback_modules(
    root: Path,
    requested_domains: set[str],
    tiers: Mapping[str, str],
    domains: Mapping[str, str],
) -> list[str]:
    """Materialize fast modules so fallback cannot filter out known observers."""
    if not requested_domains:
        return []
    modules = []
    for path in sorted((root / "tests").rglob("*.py")):
        if tiers.get(path.stem) not in {"unit", "contract"}:
            continue
        if (
            "all" not in requested_domains
            and domains.get(path.stem) not in requested_domains
        ):
            continue
        relative = path.relative_to(root).as_posix()
        _pytest_module(relative)
        if not path.resolve().is_relative_to(root):
            raise ImpactSelectionError(
                f"fallback test is outside the repository: {relative}"
            )
        modules.append(relative)
    return modules


def select_impacted_tests(
    *,
    graph_path: Path,
    source_root: Path,
    observer_path: Path,
    declarations: tuple[str, ...],
    changed_tests: tuple[str, ...] = (),
    classification_path: Path = Path("tests/conftest.py"),
    analyzed_roots: frozenset[str] = ANALYZED_SOURCE_ROOTS,
) -> dict[str, object]:
    """Keep known observers while widening every explicit coverage gap."""
    root = source_root.resolve()
    graph = load_source_graph(graph_path, root, analyzed_roots)
    manifest = load_observers(observer_path)
    tiers, domains = _test_classification(classification_path)
    try:
        selection = testing.select_graph_tests(
            graph,
            source_root=root,
            framework="pytest",
            declarations=declarations,
            observers={key: value.tests for key, value in manifest.observers.items()},
            changed_tests=changed_tests,
        )
    except (ValueError, OSError) as error:
        raise ImpactSelectionError(str(error)) from error

    nodes = {node.node_id: node for node in graph.nodes}
    fallback_domains = {
        _fallback_domain(str(declaration), nodes, manifest, domains)
        for declaration in selection.unresolved
    }
    if selection.analysis_unknowns:
        fallback_domains.add("all")

    selected = [str(reference) for reference in selection.known_tests]
    for reference in selected:
        _pytest_module(reference)
    unknown_tests = sorted(
        reference
        for reference in selected
        if PurePosixPath(_pytest_module(reference)).stem not in tiers
    )
    if unknown_tests:
        raise ImpactSelectionError(
            f"observing tests lack tier ownership: {unknown_tests}"
        )
    active_tests = sorted(
        reference
        for reference in selected
        if tiers[PurePosixPath(_pytest_module(reference)).stem] in {"unit", "contract"}
    )
    deferred_tests = sorted(set(selected) - set(active_tests))
    fallback_modules = _fallback_modules(root, fallback_domains, tiers, domains)
    available_fallback_domains = {
        domains[PurePosixPath(module).stem] for module in fallback_modules
    }
    if fallback_modules:
        available_fallback_domains.add("all")
    uncovered_fallback_domains = sorted(fallback_domains - available_fallback_domains)
    # A module already includes its selected node IDs. Preserve their identity
    # in selected_tests while avoiding duplicate execution in the command.
    pytest_args = sorted(
        set(fallback_modules)
        | {
            reference
            for reference in active_tests
            if _pytest_module(reference) not in fallback_modules
        }
    )
    mode = (
        "fast_repository"
        if "all" in fallback_domains
        else "domain"
        if fallback_domains
        else "nodeids"
    )
    targets = set(selection.target_node_ids)
    neighbors = sorted(
        {
            edge.source
            for edge in graph.edges
            if edge.target in targets and edge.kind != "imports"
        }
    )
    if (
        codeql.source_digest(root, graph.snapshot.analyzed_roots)
        != graph.snapshot.source_sha256
    ):
        raise ImpactSelectionError("source changed during test selection")
    return {
        "schema_version": 1,
        "mode": mode,
        "targets": sorted(set(declarations)),
        "target_ast_bindings": [
            {
                "node_id": node.node_id,
                "path": node.path,
                "symbol": node.symbol,
                "line": node.binding_start_line,
                "byte_column": node.binding_start_col,
            }
            for node in graph.nodes
            if node.node_id in targets
        ],
        "one_hop_neighbors": neighbors,
        "selected_tests": active_tests,
        "deferred_tests": deferred_tests,
        "incomplete_declarations": list(selection.unresolved),
        "analysis_unknowns": list(selection.analysis_unknowns),
        "fallback_domains": sorted(fallback_domains),
        "fallback_modules": fallback_modules,
        "uncovered_fallback_domains": uncovered_fallback_domains,
        "pytest_args": pytest_args,
        "complete": selection.complete,
        "requires_manual_selection": (
            not pytest_args or bool(uncovered_fallback_domains)
        ),
    }


def _parser() -> argparse.ArgumentParser:
    """Define the VIPER adapter command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--observers", required=True, type=Path)
    parser.add_argument("--declaration", action="append", required=True)
    parser.add_argument("--changed-test", action="append", default=[])
    parser.add_argument("--analyzed-root", action="append", dest="analyzed_roots")
    parser.add_argument(
        "--classifications", type=Path, default=Path("tests/conftest.py")
    )
    return parser


def main() -> int:
    """Print selection evidence and refuse a runnable-plan claim without coverage."""
    arguments = _parser().parse_args()
    result = select_impacted_tests(
        graph_path=arguments.graph,
        source_root=arguments.source_root,
        observer_path=arguments.observers,
        declarations=tuple(arguments.declaration),
        changed_tests=tuple(arguments.changed_test),
        classification_path=arguments.classifications,
        analyzed_roots=frozenset(arguments.analyzed_roots or ANALYZED_SOURCE_ROOTS),
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 1 if result["requires_manual_selection"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
