"""Observe VIPER's adapter against current, fully typed graph fixtures."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from source_impact import codeql, models

from tools.select_impacted_tests import (
    ImpactSelectionError,
    select_impacted_tests,
    source_digest,
)
from tools.select_unittest_tests import select_unittest_tests

Dependency = tuple[str, str, models.EdgeKind]
ROOTS = frozenset({"src", "tests", "tools"})
TARGET = "src/viper/storage.py:LocalArtifactStore"
CALLER = "src/viper/authoring.py:_freeze_input"
IDENTITY = "tests/test_storage.py:test_store_identity"


@dataclass(frozen=True)
class ImpactFiles:
    """Keep the actual source and adapter-policy files for one controlled graph."""

    root: Path
    graph: Path
    observers: Path
    classifications: Path


def _sha(value: bytes) -> str:
    """Hash the explicit fixture bytes named by a receipt."""
    return hashlib.sha256(value).hexdigest()


def _node(
    path: str,
    source: str,
    symbol: str,
    kind: models.SourceNodeKind,
    declaration: ast.stmt,
    binding: ast.stmt | ast.expr | ast.alias,
) -> models.SourceNode:
    """Describe exact fixture AST positions without pretending CodeQL executed."""
    assert declaration.end_lineno is not None
    assert declaration.end_col_offset is not None
    assert binding.end_lineno is not None
    assert binding.end_col_offset is not None
    start = declaration.lineno
    if isinstance(declaration, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        start = min([start, *(item.lineno for item in declaration.decorator_list)])
    lines = source.encode("utf-8").splitlines(keepends=True)
    selected = lines[start - 1 : declaration.end_lineno]
    if len(selected) == 1:
        exact = selected[0][declaration.col_offset : declaration.end_col_offset]
    else:
        exact = (
            selected[0][declaration.col_offset :]
            + b"".join(selected[1:-1])
            + selected[-1][: declaration.end_col_offset]
        )
    return models.SourceNode(
        node_id=f"{path}:{binding.lineno}:{binding.col_offset}",
        path=path,
        symbol=symbol,
        kind=kind,
        binding_start_line=binding.lineno,
        binding_start_col=binding.col_offset,
        binding_end_line=binding.end_lineno,
        binding_end_col=binding.end_col_offset,
        start_line=start,
        start_col=declaration.col_offset,
        end_line=declaration.end_lineno,
        end_col=declaration.end_col_offset,
        sha256=_sha(exact),
    )


def _nodes(root: Path) -> tuple[models.SourceNode, ...]:
    """Describe every module/class declaration in these bounded fixture files."""
    result: list[models.SourceNode] = []

    def visit(path: str, source: str, body: list[ast.stmt], prefix: str = "") -> None:
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.append(
                    _node(
                        path,
                        source,
                        prefix + statement.name,
                        "method" if prefix else "function",
                        statement,
                        statement,
                    )
                )
            elif isinstance(statement, ast.ClassDef):
                result.append(
                    _node(
                        path,
                        source,
                        prefix + statement.name,
                        "class",
                        statement,
                        statement,
                    )
                )
                visit(path, source, statement.body, prefix + statement.name + ".")
            elif isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        result.append(
                            _node(
                                path,
                                source,
                                prefix + target.id,
                                "assignment",
                                statement,
                                target,
                            )
                        )
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    if alias.name != "*":
                        result.append(
                            _node(
                                path,
                                source,
                                prefix + (alias.asname or alias.name),
                                "import",
                                statement,
                                alias,
                            )
                        )

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        visit(relative, source, ast.parse(source).body)
    return tuple(result)


def _publish(
    files: ImpactFiles,
    dependencies: tuple[Dependency, ...] = (
        (CALLER, TARGET, "constructs"),
        (IDENTITY, TARGET, "calls"),
    ),
    unknowns: tuple[str, ...] = (),
) -> models.SourceGraph:
    """Write a full current graph with controlled facts and valid receipt keys."""
    nodes = _nodes(files.root)
    by_name = {f"{node.path}:{node.symbol}": node for node in nodes}
    edges = tuple(
        models.SourceEdge(
            edge_id=_sha(f"{source}:{target}:{kind}".encode()),
            source=by_name[source].node_id,
            target=by_name[target].node_id,
            kind=kind,
            query="fixture/controlled-dependencies",
            path=by_name[source].path,
            line=by_name[source].binding_start_line,
        )
        for source, target, kind in dependencies
    )
    snapshot = models.SourceSnapshot(
        source_sha256=codeql.source_digest(files.root, ROOTS),
        analyzed_roots=tuple(sorted(ROOTS)),
    )
    extraction = models.CodeQLExtractionSpec(
        version="fixture",
        platform="fixture",
        executable_sha256=_sha(b"fixture executable"),
        extractor_sha256=_sha(b"fixture extractor"),
    )
    database = models.DatabaseReceipt(
        snapshot=snapshot,
        extraction=extraction,
        key=models.stage_key(snapshot.source_sha256, extraction),
        sha256=_sha(b"fixture database"),
        commands=(("fixture", "database"),),
        stderr_sha256=_sha(b""),
    )
    query_spec = codeql.resolve_query_spec()
    query = models.QueryReceipt(
        database_key=database.key,
        database_sha256=database.sha256,
        query=query_spec,
        key=models.stage_key(database.key, database.sha256, query_spec),
        sha256=_sha(b"fixture query rows"),
        commands=(("fixture", "query"),),
        stderr_sha256=_sha(b""),
    )
    format = models.SourceGraphFormat(lowering_sha256=codeql.lowering_digest())
    receipt = models.GraphReceipt(
        query_key=query.key,
        query_sha256=query.sha256,
        format=format,
        key=models.stage_key(query.key, query.sha256, format),
        sha256=models.graph_content_digest(nodes, edges, unknowns),
        commands=(("fixture", "decode"),),
        stderr_sha256=_sha(b""),
    )
    graph = models.SourceGraph(
        snapshot=snapshot,
        nodes=nodes,
        edges=edges,
        analysis_unknowns=unknowns,
        receipt=models.CodeQLAnalysisReceipt(
            database=database,
            query=query,
            graph=receipt,
        ),
    )
    files.graph.write_text(graph.model_dump_json(), encoding="utf-8")
    return graph


@pytest.fixture
def impact_files(tmp_path: Path) -> ImpactFiles:
    """Write real callable sources plus VIPER-owned tier/domain policy."""
    root = tmp_path / "source"
    for name in ROOTS:
        (root / name).mkdir(parents=True)
    sources = {
        "src/viper/storage.py": "class LocalArtifactStore:\n    pass\n",
        "src/viper/authoring.py": (
            "from .storage import LocalArtifactStore\n"
            "def _freeze_input():\n    return LocalArtifactStore()\n"
        ),
        "tests/test_storage.py": (
            "from src.viper.storage import LocalArtifactStore\n"
            "def test_direct():\n    assert LocalArtifactStore() is not None\n"
            "def test_store_identity():\n    assert LocalArtifactStore() is not None\n"
        ),
        "tests/test_prior_run_inputs.py": ("def test_caller():\n    assert True\n"),
        "tests/conftest.py": (
            "TIER_BY_MODULE = {'test_storage': 'unit', "
            "'test_prior_run_inputs': 'contract', 'test_nested': 'unit'}\n"
            "DOMAIN_BY_MODULE = {'test_storage': 'domain_storage', "
            "'test_prior_run_inputs': 'domain_authoring', "
            "'test_nested': 'domain_storage'}\n"
        ),
    }
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    observers = tmp_path / "observers.toml"
    observers.write_text(
        """schema_version = 1
[source_domains]
"src/viper/authoring.py" = "domain_authoring"
"src/viper/storage.py" = "domain_storage"

[[declarations]]
id = "src/viper/storage.py:LocalArtifactStore"
fallback_domain = "domain_storage"
tests = ["tests/test_storage.py::test_direct"]

[[declarations]]
id = "src/viper/authoring.py:_freeze_input"
fallback_domain = "domain_authoring"
tests = ["tests/test_prior_run_inputs.py::test_caller"]
""",
        encoding="utf-8",
    )
    files = ImpactFiles(
        root=root,
        graph=tmp_path / "source-graph.json",
        observers=observers,
        classifications=root / "tests/conftest.py",
    )
    _publish(files)
    return files


def _select(
    files: ImpactFiles, declarations: tuple[str, ...] = (TARGET,)
) -> dict[str, object]:
    """Exercise the real loader, shared selector, and VIPER policy adapter."""
    return select_impacted_tests(
        graph_path=files.graph,
        source_root=files.root,
        observer_path=files.observers,
        declarations=declarations,
        classification_path=files.classifications,
    )


def _remove_caller_observer(files: ImpactFiles) -> None:
    """Leave the production consumer without its explicit observing test."""
    text = files.observers.read_text(encoding="utf-8")
    files.observers.write_text(
        text.rsplit("\n[[declarations]]\n", 1)[0], encoding="utf-8"
    )


def test_selects_target_and_transitive_observers(impact_files: ImpactFiles) -> None:
    """Retain explicit target/consumer observers and the graph's direct test."""
    result = _select(impact_files)
    assert result["mode"] == "nodeids"
    assert result["selected_tests"] == [
        "tests/test_prior_run_inputs.py::test_caller",
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]
    assert result["pytest_args"] == result["selected_tests"]
    assert result["complete"] is True
    assert result["target_ast_bindings"] == [
        {
            "node_id": "src/viper/storage.py:1:0",
            "path": "src/viper/storage.py",
            "symbol": "LocalArtifactStore",
            "line": 1,
            "byte_column": 0,
        }
    ]


def test_uncovered_branch_unions_its_domain_with_known_tests(
    impact_files: ImpactFiles,
) -> None:
    """Domain fallback cannot remove already selected tests from another domain."""
    _remove_caller_observer(impact_files)
    result = _select(impact_files)

    assert result["mode"] == "domain"
    assert result["fallback_domains"] == ["domain_authoring"]
    assert result["incomplete_declarations"] == ["src/viper/authoring.py:2:0"]
    assert result["pytest_args"] == [
        "tests/test_prior_run_inputs.py",
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]
    assert result["complete"] is False
    assert result["requires_manual_selection"] is False


def test_one_available_fallback_domain_cannot_hide_another_missing_domain(
    impact_files: ImpactFiles,
) -> None:
    """Keep known tests but require selection for each domain without a suite."""
    _remove_caller_observer(impact_files)
    impact_files.observers.write_text(
        impact_files.observers.read_text(encoding="utf-8")
        + """
[[declarations]]
id = "src/viper/storage.py:missing"
fallback_domain = "domain_metrics"
tests = ["tests/test_storage.py::test_direct"]
""",
        encoding="utf-8",
    )
    result = _select(
        impact_files,
        (TARGET, "src/viper/storage.py:missing"),
    )

    assert result["fallback_domains"] == ["domain_authoring", "domain_metrics"]
    assert result["fallback_modules"] == ["tests/test_prior_run_inputs.py"]
    assert result["uncovered_fallback_domains"] == ["domain_metrics"]
    assert result["incomplete_declarations"] == [
        "src/viper/authoring.py:2:0",
        "src/viper/storage.py:missing",
    ]
    assert result["pytest_args"] == [
        "tests/test_prior_run_inputs.py",
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]
    assert result["complete"] is False
    assert result["requires_manual_selection"] is True


def test_unmapped_consumer_uses_its_graph_observer(impact_files: ImpactFiles) -> None:
    """A reachable test resolves the consumer without an explicit observer row."""
    _remove_caller_observer(impact_files)
    _publish(
        impact_files,
        (
            (CALLER, TARGET, "constructs"),
            (IDENTITY, TARGET, "calls"),
            (IDENTITY, CALLER, "calls"),
        ),
    )
    result = _select(impact_files)
    assert result["fallback_domains"] == []
    assert result["pytest_args"] == [
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]


def test_unobserved_import_carrier_retains_a_coverage_gap(
    impact_files: ImpactFiles,
) -> None:
    """A covered branch does not silently account for an unread import binding."""
    imported = "src/viper/authoring.py:LocalArtifactStore"
    graph = _publish(
        impact_files,
        (
            (CALLER, TARGET, "constructs"),
            (IDENTITY, TARGET, "calls"),
            (imported, TARGET, "imports"),
        ),
    )
    binding = next(
        node.node_id for node in graph.nodes if f"{node.path}:{node.symbol}" == imported
    )
    result = _select(impact_files)
    neighbors = result["one_hop_neighbors"]
    assert isinstance(neighbors, list)
    assert binding not in neighbors
    assert result["incomplete_declarations"] == [binding]
    assert result["fallback_domains"] == ["domain_authoring"]


@pytest.mark.parametrize("kind", ["assignment", "import"])
def test_unobserved_carrier_uses_its_source_domain(
    impact_files: ImpactFiles,
    kind: str,
) -> None:
    """Unobserved non-callable declarations retain the owning fallback domain."""
    source = impact_files.root / "src/viper/authoring.py"
    addition = (
        "unobserved_assignment = 1\n"
        if kind == "assignment"
        else "import pathlib as unobserved_import\n"
    )
    source.write_text(source.read_text(encoding="utf-8") + addition, encoding="utf-8")
    _publish(impact_files)
    result = _select(impact_files, (f"src/viper/authoring.py:unobserved_{kind}",))
    assert result["mode"] == "domain"
    assert result["fallback_domains"] == ["domain_authoring"]
    assert result["pytest_args"] == ["tests/test_prior_run_inputs.py"]


def test_missing_target_uses_explicit_declaration_domain_first(
    impact_files: ImpactFiles,
) -> None:
    """A declaration's fallback owner takes precedence over its file's domain."""
    impact_files.observers.write_text(
        impact_files.observers.read_text(encoding="utf-8")
        + """
[[declarations]]
id = "src/viper/storage.py:missing"
fallback_domain = "domain_authoring"
tests = ["tests/test_storage.py::test_direct"]
""",
        encoding="utf-8",
    )
    result = _select(impact_files, ("src/viper/storage.py:missing",))
    assert result["fallback_domains"] == ["domain_authoring"]
    assert result["pytest_args"] == [
        "tests/test_prior_run_inputs.py",
        "tests/test_storage.py::test_direct",
    ]
    assert result["incomplete_declarations"] == ["src/viper/storage.py:missing"]


def test_absent_unowned_target_materializes_all_fast_modules(
    impact_files: ImpactFiles,
) -> None:
    """A missing owner widens the actual command to existing fast modules."""
    result = _select(impact_files, ("src/viper/missing.py:missing",))
    assert result["mode"] == "fast_repository"
    assert result["pytest_args"] == [
        "tests/test_prior_run_inputs.py",
        "tests/test_storage.py",
    ]


def test_explicit_analysis_unknowns_survive_native_loading(
    impact_files: ImpactFiles,
) -> None:
    """Known observers coexist with a retained limitation and conservative union."""
    reason = "src/viper/storage.py: external registry binding is unresolved"
    _publish(impact_files, unknowns=(reason,))
    result = _select(impact_files)
    assert result["analysis_unknowns"] == [reason]
    assert result["complete"] is False
    assert result["fallback_domains"] == ["all"]
    assert result["pytest_args"] == [
        "tests/test_prior_run_inputs.py",
        "tests/test_storage.py",
    ]
    assert result["selected_tests"] == [
        "tests/test_prior_run_inputs.py::test_caller",
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]


def test_nested_test_module_reusing_a_test_is_selected(
    impact_files: ImpactFiles,
) -> None:
    """A collected test cannot stop traversal to another directory's test."""
    path = impact_files.root / "tests/nested/test_nested.py"
    path.parent.mkdir()
    path.write_text(
        "from tests.test_storage import test_store_identity\n"
        "def test_nested():\n    test_store_identity()\n",
        encoding="utf-8",
    )
    _publish(
        impact_files,
        (
            (CALLER, TARGET, "constructs"),
            (IDENTITY, TARGET, "calls"),
            ("tests/nested/test_nested.py:test_nested", IDENTITY, "calls"),
        ),
    )
    result = _select(impact_files)
    selected = result["selected_tests"]
    assert isinstance(selected, list)
    assert "tests/nested/test_nested.py::test_nested" in selected
    assert result["complete"] is True


def test_test_prefixed_assignment_is_not_a_collected_observer(
    impact_files: ImpactFiles,
) -> None:
    """An assignment retains its gap instead of becoming an invalid pytest node."""
    path = impact_files.root / "tests/test_storage.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "test_configuration = LocalArtifactStore\n",
        encoding="utf-8",
    )
    graph = _publish(
        impact_files,
        (
            (CALLER, TARGET, "constructs"),
            (IDENTITY, TARGET, "calls"),
            ("tests/test_storage.py:test_configuration", TARGET, "reads"),
        ),
    )
    assignment = next(
        node.node_id for node in graph.nodes if node.symbol == "test_configuration"
    )
    result = _select(impact_files)
    selected = result["selected_tests"]
    assert isinstance(selected, list)
    assert "tests/test_storage.py::test_configuration" not in selected
    assert result["incomplete_declarations"] == [assignment]
    assert result["pytest_args"] == [
        "tests/test_prior_run_inputs.py::test_caller",
        "tests/test_storage.py",
    ]


def test_unittest_adapter_keeps_known_tests_beside_fallback(
    impact_files: ImpactFiles,
) -> None:
    """The compatibility adapter never replaces a known case with its fallback."""
    path = impact_files.root / "tests/nested/test_cases.py"
    path.parent.mkdir()
    path.write_text(
        "from unittest import TestCase as Base\n"
        "class Checks(Base):\n"
        "    def test_read(self):\n        self.assertEqual(1, 1)\n",
        encoding="utf-8",
    )
    _publish(
        impact_files,
        (
            (CALLER, TARGET, "constructs"),
            ("tests/nested/test_cases.py:Checks.test_read", TARGET, "calls"),
        ),
    )
    result = select_unittest_tests(
        graph_path=impact_files.graph,
        source_root=impact_files.root,
        declarations=(TARGET,),
        analyzed_roots=ROOTS,
        fallback="tests.test_fallback",
    )
    assert result["selected_tests"] == ("tests.nested.test_cases.Checks.test_read",)
    assert result["unittest_args"] == (
        "tests.nested.test_cases.Checks.test_read",
        "tests.test_fallback",
    )
    assert result["complete"] is False


def test_rejects_dangling_graph_edges(impact_files: ImpactFiles) -> None:
    """Full typed validation rejects missing endpoints before claiming a plan."""
    payload = json.loads(impact_files.graph.read_text(encoding="utf-8"))
    payload["nodes"] = [
        node for node in payload["nodes"] if node["symbol"] != "test_store_identity"
    ]
    impact_files.graph.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ImpactSelectionError, match="unknown endpoint"):
        _select(impact_files)


def test_rejects_stale_source(impact_files: ImpactFiles) -> None:
    """Even a supplied fallback cannot turn historical facts into current facts."""
    (impact_files.root / "src/viper/storage.py").write_text("CHANGED = True\n")
    with pytest.raises(ImpactSelectionError, match="source"):
        _select(impact_files)


def test_source_identity_respects_explicit_roots(tmp_path: Path) -> None:
    """Excluded source changes do not alter an explicitly bounded inventory."""
    selected = tmp_path / "contract_protocol/package.py"
    ignored = tmp_path / "archive/old.py"
    selected.parent.mkdir()
    ignored.parent.mkdir()
    selected.write_text("VALUE = 1\n", encoding="utf-8")
    ignored.write_text("VALUE = 1\n", encoding="utf-8")
    digest = source_digest(tmp_path, frozenset({"contract_protocol"}))
    ignored.write_text("VALUE = 2\n", encoding="utf-8")
    assert source_digest(tmp_path, frozenset({"contract_protocol"})) == digest
