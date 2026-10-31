"""Verify the unittest adapter against full current source-graph records."""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

from source_impact import codeql, models

from tools.select_unittest_tests import select_unittest_tests
from viper import _subprocess

ANALYZED_ROOTS = frozenset({"contract_protocol", "tests"})
TEST_REFERENCE = (
    "tests.contract_protocol.test_compiler.CompilerTests.test_compile_state"
)


def _sha(value: bytes) -> str:
    """Hash the explicit fixture input named by a source or analysis record."""
    return hashlib.sha256(value).hexdigest()


def _node(
    path: str,
    source: str,
    symbol: str,
    kind: models.SourceNodeKind,
    declaration: ast.stmt,
    binding: ast.alias | None = None,
) -> models.SourceNode:
    """Bind one controlled declaration to its actual AST and exact source bytes."""
    occurrence = declaration if binding is None else binding
    assert declaration.end_lineno is not None
    assert declaration.end_col_offset is not None
    assert occurrence.end_lineno is not None
    assert occurrence.end_col_offset is not None
    excerpt = ast.get_source_segment(source, declaration)
    assert excerpt is not None
    return models.SourceNode(
        node_id=f"{path}:{occurrence.lineno}:{occurrence.col_offset}",
        path=path,
        symbol=symbol,
        kind=kind,
        binding_start_line=occurrence.lineno,
        binding_start_col=occurrence.col_offset,
        binding_end_line=occurrence.end_lineno,
        binding_end_col=occurrence.end_col_offset,
        start_line=declaration.lineno,
        start_col=declaration.col_offset,
        end_line=declaration.end_lineno,
        end_col=declaration.end_col_offset,
        sha256=_sha(excerpt.encode("utf-8")),
    )


def _write_graph(
    root: Path,
    graph_path: Path,
    unknowns: tuple[str, ...] = (),
) -> None:
    """Write schema-4 source evidence with controlled dependency/receipt inputs.

    The source files and AST bindings are real. Database and query bytes are
    explicit fixture inputs; this helper does not claim a CodeQL execution.
    """
    production_path = "contract_protocol/compiler.py"
    test_path = "tests/contract_protocol/test_compiler.py"
    production_source = "def compile_state():\n    return 'compiled'\n"
    test_source = (
        "import unittest\n"
        "from contract_protocol.compiler import compile_state\n"
        "class CompilerTests(unittest.TestCase):\n"
        "    def test_compile_state(self):\n"
        "        self.assertEqual(compile_state(), 'compiled')\n"
    )
    sources = {
        "contract_protocol/__init__.py": "",
        "tests/__init__.py": "",
        "tests/contract_protocol/__init__.py": "",
        production_path: production_source,
        test_path: test_source,
    }
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    function = ast.parse(production_source).body[0]
    base_import, function_import, test_class = ast.parse(test_source).body
    assert isinstance(function, ast.FunctionDef)
    assert isinstance(base_import, ast.Import)
    assert isinstance(function_import, ast.ImportFrom)
    assert isinstance(test_class, ast.ClassDef)
    method = test_class.body[0]
    assert isinstance(method, ast.FunctionDef)
    owner = _node(
        production_path,
        production_source,
        "compile_state",
        "function",
        function,
    )
    imported_owner = _node(
        test_path,
        test_source,
        "compile_state",
        "import",
        function_import,
        function_import.names[0],
    )
    observer = _node(
        test_path,
        test_source,
        "CompilerTests.test_compile_state",
        "method",
        method,
    )
    nodes = (
        owner,
        _node(
            test_path,
            test_source,
            "unittest",
            "import",
            base_import,
            base_import.names[0],
        ),
        imported_owner,
        _node(test_path, test_source, "CompilerTests", "class", test_class),
        observer,
    )
    dependencies: tuple[
        tuple[models.SourceNode, models.SourceNode, models.EdgeKind], ...
    ] = (
        (imported_owner, owner, "imports"),
        (observer, imported_owner, "reads"),
        (observer, owner, "calls"),
    )
    edges = tuple(
        models.SourceEdge(
            edge_id=_sha(f"{caller.node_id}:{callee.node_id}:{kind}".encode()),
            source=caller.node_id,
            target=callee.node_id,
            kind=kind,
            query="fixture/controlled-dependencies",
            path=caller.path,
            line=caller.binding_start_line,
        )
        for caller, callee, kind in dependencies
    )
    snapshot = models.SourceSnapshot(
        source_sha256=codeql.source_digest(root, ANALYZED_ROOTS),
        analyzed_roots=tuple(sorted(ANALYZED_ROOTS)),
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
    graph_format = models.SourceGraphFormat(lowering_sha256=codeql.lowering_digest())
    receipt = models.GraphReceipt(
        query_key=query.key,
        query_sha256=query.sha256,
        format=graph_format,
        key=models.stage_key(query.key, query.sha256, graph_format),
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
    graph_path.write_text(graph.model_dump_json(), encoding="utf-8")


def test_returns_importable_unittest_name(tmp_path: Path) -> None:
    """Retain an actual TestCase method and every explicitly supplied fallback."""
    graph = tmp_path / "graph.json"
    _write_graph(tmp_path, graph)

    result = select_unittest_tests(
        graph_path=graph,
        source_root=tmp_path,
        declarations=("contract_protocol/compiler.py:compile_state",),
        analyzed_roots=ANALYZED_ROOTS,
        fallback="tests.contract_protocol.test_compiler",
    )

    assert result["mode"] == "tests_and_fallback"
    assert result["selected_tests"] == (TEST_REFERENCE,)
    assert result["unittest_args"] == (
        "tests.contract_protocol.test_compiler",
        TEST_REFERENCE,
    )
    assert result["complete"] is True
    assert result["requires_manual_selection"] is False


def test_uses_fallback_for_unresolved_declaration(tmp_path: Path) -> None:
    """Return the declared suite while retaining the exact unresolved request."""
    graph = tmp_path / "graph.json"
    _write_graph(tmp_path, graph)

    result = select_unittest_tests(
        graph_path=graph,
        source_root=tmp_path,
        declarations=("contract_protocol/compiler.py:missing",),
        analyzed_roots=ANALYZED_ROOTS,
        fallback="tests.contract_protocol.test_compiler",
    )

    assert result["mode"] == "fallback"
    assert result["selected_tests"] == ()
    assert result["unittest_args"] == ("tests.contract_protocol.test_compiler",)
    assert result["unresolved"] == ("contract_protocol/compiler.py:missing",)
    references = result["unittest_args"]
    assert isinstance(references, tuple)
    actual = _subprocess.run(
        [sys.executable, "-m", "unittest", *references],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert actual.returncode == 0, actual.stdout + actual.stderr
    assert "Ran 1 test" in actual.stderr
    assert result["complete"] is False
    assert result["requires_manual_selection"] is False


def test_graph_unknowns_survive_with_known_unittest_and_fallback(
    tmp_path: Path,
) -> None:
    """A reachable method cannot erase a retained static-analysis limitation."""
    graph = tmp_path / "graph.json"
    reason = "contract_protocol/compiler.py: external registry binding is unresolved"
    _write_graph(tmp_path, graph, unknowns=(reason,))

    result = select_unittest_tests(
        graph_path=graph,
        source_root=tmp_path,
        declarations=("contract_protocol/compiler.py:compile_state",),
        analyzed_roots=ANALYZED_ROOTS,
        fallback="tests.contract_protocol.test_compiler",
    )

    assert result["mode"] == "fallback"
    assert result["selected_tests"] == (TEST_REFERENCE,)
    assert result["unittest_args"] == (
        "tests.contract_protocol.test_compiler",
        TEST_REFERENCE,
    )
    assert result["analysis_unknowns"] == (reason,)
    assert result["complete"] is False
