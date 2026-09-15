"""Select declaration-linked pytest checks from a CodeQL source graph."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from viper.test_impact import DeclarationId, TestRef, select_tests

IGNORED_SOURCE_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".viper",
        "node_modules",
    }
)
ANALYZED_SOURCE_ROOTS = frozenset({"src", "tests", "tools"})


class ImpactSelectionError(ValueError):
    """Report an invalid source graph, observer manifest, or target selection."""


@dataclass(frozen=True, slots=True)
class DeclarationObserver:
    """Link one source declaration to its tests and conservative fallback domain."""

    declaration: str
    tests: tuple[str, ...]
    fallback_domain: str


@dataclass(frozen=True, slots=True)
class ImpactManifest:
    """Hold declaration observers and source-file fallback ownership."""

    observers: dict[str, DeclarationObserver]
    source_domains: dict[str, str]


def source_digest(
    root: Path,
    analyzed_roots: frozenset[str] = ANALYZED_SOURCE_ROOTS,
) -> str:
    """Hash Python paths and bytes exactly as the inherited graph lowerer does."""
    rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(
            (
                candidate
                for candidate in root.rglob("*.py")
                if candidate.relative_to(root).parts[0] in analyzed_roots
                if not any(
                    part in IGNORED_SOURCE_PARTS
                    for part in candidate.relative_to(root).parts
                )
            ),
            key=lambda candidate: candidate.relative_to(root).as_posix(),
        )
    ]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_observers(path: Path) -> ImpactManifest:
    """Load the unique declaration-to-test records from one TOML manifest."""
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
            or not all(
                isinstance(test, str)
                and test.startswith("tests/test_")
                and "::" in test
                for test in tests
            )
        ):
            raise ImpactSelectionError(f"invalid observing tests for {declaration}")
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
    """Read pytest tier and domain maps without importing test configuration."""
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
        return assignments["TIER_BY_MODULE"], assignments["DOMAIN_BY_MODULE"]
    except KeyError as error:
        raise ImpactSelectionError("pytest classification maps are missing") from error


def _test_module(node_id: str) -> str:
    """Return the Python module stem selected by one pytest node ID."""
    return Path(node_id.split("::", 1)[0]).stem


def load_source_graph(
    path: Path,
    source_root: Path,
    analyzed_roots: frozenset[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load the version-3 graph emitted by VIPER's CodeQL/AST lowerer."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 3:
        raise ImpactSelectionError("source graph schema_version must equal 3")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("source_sha256") != source_digest(
        source_root, analyzed_roots
    ):
        raise ImpactSelectionError("source graph does not describe the current source")
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ImpactSelectionError("source graph needs node and edge lists")

    nodes: dict[str, dict[str, Any]] = {}
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise ImpactSelectionError("source graph node must be an object")
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or node_id in nodes:
            raise ImpactSelectionError("source graph node IDs must be unique strings")
        for field in ("path", "symbol", "binding_start_line", "binding_start_col"):
            if field not in node:
                raise ImpactSelectionError(
                    f"source graph node lacks {field}: {node_id}"
                )
        nodes[node_id] = node

    edges: list[dict[str, Any]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            raise ImpactSelectionError("source graph edge must be an object")
        source = edge.get("source")
        target = edge.get("target")
        if source not in nodes or target not in nodes:
            raise ImpactSelectionError("source graph edge references an absent node")
        edges.append(edge)
    return nodes, edges


def _pytest_node_id(node: dict[str, Any]) -> str | None:
    """Convert one CodeQL/AST test declaration into its pytest node ID."""
    path = node["path"]
    symbol = node["symbol"]
    if not (
        isinstance(path, str)
        and path.startswith("tests/test_")
        and isinstance(symbol, str)
        and (symbol.startswith("test_") or ".test_" in symbol)
    ):
        return None
    return f"{path}::{symbol.replace('.', '::')}"


def select_impacted_tests(
    *,
    graph_path: Path,
    source_root: Path,
    observer_path: Path,
    declarations: tuple[str, ...],
    changed_tests: tuple[str, ...] = (),
    classification_path: Path = Path("tests/conftest.py"),
    analyzed_roots: frozenset[str] = ANALYZED_SOURCE_ROOTS,
) -> dict[str, Any]:
    """Select impacted tests or widen when graph coverage remains incomplete."""
    if not declarations:
        raise ImpactSelectionError("at least one changed declaration is required")

    nodes, edges = load_source_graph(
        graph_path,
        source_root.resolve(),
        analyzed_roots,
    )
    manifest = load_observers(observer_path)
    observers = manifest.observers
    tier_by_module, domain_by_module = _test_classification(classification_path)
    target_set = set(declarations)
    missing_targets = {
        DeclarationId(declaration) for declaration in target_set - nodes.keys()
    }

    fallback_domains: set[str] = set()
    incoming: dict[str, set[str]] = {}
    for edge in edges:
        incoming.setdefault(str(edge["target"]), set()).add(str(edge["source"]))

    neighbors = sorted(
        {
            str(edge["source"])
            for edge in edges
            if edge.get("target") in target_set and edge.get("kind") != "imports"
        }
    )

    dependents = {
        DeclarationId(declaration): {
            DeclarationId(dependent) for dependent in declaration_dependents
        }
        for declaration, declaration_dependents in incoming.items()
    }
    observer_refs = {
        DeclarationId(declaration): tuple(TestRef(test) for test in observer.tests)
        for declaration, observer in observers.items()
    }
    test_refs_by_declaration = {
        DeclarationId(declaration): TestRef(test)
        for declaration, node in nodes.items()
        if (test := _pytest_node_id(node)) is not None
    }

    selection = select_tests(
        (DeclarationId(declaration) for declaration in target_set | set(neighbors)),
        dependents=dependents,
        observers=observer_refs,
        test_refs_by_declaration=test_refs_by_declaration,
    )

    selected_tests: set[str] = set(changed_tests)
    selected_tests.update(selection.tests)
    incomplete_declarations = set(selection.unresolved) | missing_targets
    for declaration in incomplete_declarations:
        node = nodes.get(declaration)
        source_path = declaration.split(":", 1)[0] if node is None else node["path"]
        if source_path.startswith("tests/test_"):
            domain = domain_by_module.get(Path(source_path).stem)
        else:
            domain = manifest.source_domains.get(source_path)
        fallback_domains.add(domain or "all")

    unknown_tests = sorted(
        test for test in selected_tests if _test_module(test) not in tier_by_module
    )
    if unknown_tests:
        raise ImpactSelectionError(
            f"observing tests lack tier ownership: {unknown_tests}"
        )
    active_tests = sorted(
        test
        for test in selected_tests
        if tier_by_module[_test_module(test)] in {"unit", "contract"}
    )
    deferred_tests = sorted(set(selected_tests) - set(active_tests))

    if "all" in fallback_domains:
        pytest_args = ["tests", "-m", "unit or contract"]
        mode = "fast_repository"
    elif fallback_domains:
        expression = " or ".join(sorted(fallback_domains))
        pytest_args = ["tests", "-m", f"({expression}) and (unit or contract)"]
        mode = "domain"
    else:
        pytest_args = active_tests
        mode = "nodeids"

    selected_nodes = [nodes[node_id] for node_id in sorted(target_set & nodes.keys())]
    return {
        "schema_version": 1,
        "mode": mode,
        "targets": sorted(target_set),
        "target_ast_bindings": [
            {
                "node_id": node["node_id"],
                "path": node["path"],
                "symbol": node["symbol"],
                "line": node["binding_start_line"],
                "byte_column": node["binding_start_col"],
            }
            for node in selected_nodes
        ],
        "one_hop_neighbors": neighbors,
        "selected_tests": active_tests,
        "deferred_tests": deferred_tests,
        "incomplete_declarations": sorted(incomplete_declarations),
        "fallback_domains": sorted(fallback_domains),
        "pytest_args": pytest_args,
    }


def _parser() -> argparse.ArgumentParser:
    """Define the command-line boundary for reproducible test selection."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--observers", required=True, type=Path)
    parser.add_argument("--declaration", action="append", required=True)
    parser.add_argument("--changed-test", action="append", default=[])
    parser.add_argument("--analyzed-root", action="append", dest="analyzed_roots")
    parser.add_argument(
        "--classifications",
        type=Path,
        default=Path("tests/conftest.py"),
    )
    return parser


def main() -> int:
    """Print one deterministic declaration-impact selection as JSON."""
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
