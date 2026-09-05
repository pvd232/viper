"""Verify exact rename obligations over baseline and candidate source graphs."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from viper._contract_traceability import RepoSymbolRef
from viper._system_impact.codeql import source_digest
from viper.system_impact.models import (
    CodeQLAnalysisReceipt,
    CodeQLExtractionSpec,
    CodeQLQuerySpec,
    DatabaseReceipt,
    GraphReceipt,
    QueryReceipt,
    SourceEdge,
    SourceGraph,
    SourceGraphFormat,
    SourceNode,
    SourceSnapshot,
    stage_key,
)
from viper.system_impact.rename import (
    RenameAnalysisError,
    RenameSpec,
    check_rename_obligations,
    compile_rename_obligations,
    render_rename_check,
)

_SHA = "0" * 64
_REVISION = "1" * 40
_EXTRACTION = CodeQLExtractionSpec(
    version="test",
    platform="test",
    executable_sha256=_SHA,
    extractor_sha256="2" * 64,
)
_QUERY = CodeQLQuerySpec(
    pack="viper/test@0.0.0",
    pack_sha256="3" * 64,
    suite="source-facts.qls",
)
_FORMAT = SourceGraphFormat(schema_version=3, lowering_sha256="4" * 64)
_SPEC = RenameSpec(
    old_target=RepoSymbolRef(path="src/viper/_subprocess.py", symbol="run"),
    new_target=RepoSymbolRef(path="src/viper/_subprocess.py", symbol="run_checked"),
    edge_kinds=("calls",),
)


def _write(root: Path, relative: str, source: str) -> None:
    """Write one source fixture beneath its repository-relative path."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _definition(
    root: Path, path: str, symbol: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef:
    """Find one top-level fixture declaration."""
    tree = ast.parse((root / path).read_text(encoding="utf-8"))
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == symbol
    ]
    assert len(matches) == 1
    return matches[0]


def _node(root: Path, path: str, symbol: str) -> SourceNode:
    """Create one represented function node from fixture source."""
    node = _definition(root, path, symbol)
    assert node.end_lineno is not None
    assert node.end_col_offset is not None
    source = (root / path).read_bytes()
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return SourceNode(
        node_id=f"{path}:{symbol}",
        path=path,
        symbol=symbol,
        kind="function",
        binding_start_line=node.lineno,
        binding_start_col=node.col_offset,
        binding_end_line=node.lineno,
        binding_end_col=node.col_offset + len(symbol),
        start_line=node.lineno,
        start_col=node.col_offset,
        end_line=node.end_lineno,
        end_col=node.end_col_offset,
        sha256=hashlib.sha256(source[start:end]).hexdigest(),
    )


def _graph(
    root: Path,
    *,
    target: str,
    caller: str = "call",
    include_edge: bool,
    committed: bool,
) -> SourceGraph:
    """Create one receipt-valid source graph for a fixture snapshot."""
    target_node = _node(root, "src/viper/_subprocess.py", target)
    caller_node = _node(root, "tests/test_use.py", caller)
    nodes = tuple(sorted((target_node, caller_node), key=lambda item: item.node_id))
    edges: tuple[SourceEdge, ...]
    if include_edge:
        payload = json.dumps(
            [
                caller_node.node_id,
                "calls",
                target_node.node_id,
                "tests/test_use.py",
                caller_node.start_line + 1,
            ],
            separators=(",", ":"),
        ).encode()
        edges = (
            SourceEdge(
                edge_id=hashlib.sha256(payload).hexdigest(),
                source=caller_node.node_id,
                target=target_node.node_id,
                kind="calls",
                query="viper/python-impact/dependencies",
                path="tests/test_use.py",
                line=caller_node.start_line + 1,
            ),
        )
    else:
        edges = ()
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=_REVISION if committed else None,
    )
    database_key = stage_key(snapshot, _EXTRACTION)
    database = DatabaseReceipt(
        snapshot=snapshot,
        extraction=_EXTRACTION,
        key=database_key,
        sha256="5" * 64,
        commands=(("codeql", "database", "create"),),
        stderr_sha256=_SHA,
    )
    query_key = stage_key(database.key, database.sha256, _QUERY)
    query = QueryReceipt(
        database_key=database.key,
        database_sha256=database.sha256,
        query=_QUERY,
        key=query_key,
        sha256="6" * 64,
        commands=(("codeql", "database", "run-queries"),),
        stderr_sha256=_SHA,
    )
    graph_payload = json.dumps(
        {
            "nodes": [item.model_dump(mode="json") for item in nodes],
            "edges": [item.model_dump(mode="json") for item in edges],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    graph_receipt = GraphReceipt(
        query_key=query.key,
        query_sha256=query.sha256,
        format=_FORMAT,
        key=stage_key(query.key, query.sha256, _FORMAT),
        sha256=hashlib.sha256(graph_payload).hexdigest(),
        commands=(("codeql", "bqrs", "decode"),),
        stderr_sha256=_SHA,
    )
    return SourceGraph(
        snapshot=snapshot,
        nodes=nodes,
        edges=edges,
        receipt=CodeQLAnalysisReceipt(
            database=database,
            query=query,
            graph=graph_receipt,
        ),
    )


def _baseline(root: Path) -> SourceGraph:
    """Write and graph the ordinary old-target fixture."""
    _write(
        root,
        "src/viper/_subprocess.py",
        "def run() -> None:\n    pass\n",
    )
    _write(
        root,
        "tests/test_use.py",
        "from viper import _subprocess as subprocess\n\n"
        "def call() -> None:\n"
        "    subprocess.run()\n",
    )
    return _graph(root, target="run", include_edge=True, committed=True)


def _candidate(root: Path, call: str) -> SourceGraph:
    """Write and graph one candidate with a new declaration."""
    _write(
        root,
        "src/viper/_subprocess.py",
        "def run_checked() -> None:\n    pass\n",
    )
    _write(
        root,
        "tests/test_use.py",
        "from viper import _subprocess as subprocess\n\n"
        "def call() -> None:\n"
        f"    subprocess.{call}()\n",
    )
    return _graph(
        root,
        target="run_checked",
        include_edge=call == "run_checked",
        committed=False,
    )


@pytest.mark.unit
@pytest.mark.domain_protocol
def test_complete_rename_satisfies_every_compiled_obligation(tmp_path: Path) -> None:
    """Accept a new declaration and exact replacement of its governed call."""
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"
    baseline = _baseline(baseline_root)
    obligations = compile_rename_obligations(
        root=baseline_root,
        graph=baseline,
        spec=_SPEC,
    )
    candidate = _candidate(candidate_root, "run_checked")

    check = check_rename_obligations(
        root=candidate_root,
        graph=candidate,
        obligations=obligations,
    )

    assert check.passed
    assert [transition.status for transition in check.transitions] == ["satisfied"]
    assert "Satisfied: 1/1 references" in render_rename_check(check)
    assert "Completion: accepted" in render_rename_check(check)


@pytest.mark.unit
@pytest.mark.domain_protocol
def test_stale_old_call_is_rejected_after_old_declaration_disappears(
    tmp_path: Path,
) -> None:
    """Reject stale syntax even when CodeQL cannot resolve the removed target."""
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"
    obligations = compile_rename_obligations(
        root=baseline_root,
        graph=_baseline(baseline_root),
        spec=_SPEC,
    )
    candidate = _candidate(candidate_root, "run")

    check = check_rename_obligations(
        root=candidate_root,
        graph=candidate,
        obligations=obligations,
    )

    assert not check.passed
    assert [transition.status for transition in check.transitions] == [
        "still_uses_old_target"
    ]
    assert "Completion: rejected" in render_rename_check(check)


@pytest.mark.unit
@pytest.mark.domain_protocol
def test_standard_library_call_does_not_satisfy_or_violate_viper_rename(
    tmp_path: Path,
) -> None:
    """Ignore the same member name when its import selects another module."""
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"
    obligations = compile_rename_obligations(
        root=baseline_root,
        graph=_baseline(baseline_root),
        spec=_SPEC,
    )
    _write(
        candidate_root,
        "src/viper/_subprocess.py",
        "def run_checked() -> None:\n    pass\n",
    )
    _write(
        candidate_root,
        "tests/test_use.py",
        "import subprocess\n"
        "from viper import _subprocess as viper_subprocess\n\n"
        "def call() -> None:\n"
        "    subprocess.run([], check=False)\n"
        "    viper_subprocess.run_checked()\n",
    )
    candidate = _graph(
        candidate_root,
        target="run_checked",
        include_edge=True,
        committed=False,
    )

    check = check_rename_obligations(
        root=candidate_root,
        graph=candidate,
        obligations=obligations,
    )

    assert check.passed
    assert check.transitions[0].candidate_old_sites == ()


@pytest.mark.unit
@pytest.mark.domain_protocol
def test_alias_rebinding_fails_closed(tmp_path: Path) -> None:
    """Reject a candidate whose target module alias changes meaning."""
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"
    obligations = compile_rename_obligations(
        root=baseline_root,
        graph=_baseline(baseline_root),
        spec=_SPEC,
    )
    _write(
        candidate_root,
        "src/viper/_subprocess.py",
        "def run_checked() -> None:\n    pass\n",
    )
    _write(
        candidate_root,
        "tests/test_use.py",
        "from viper import _subprocess as subprocess\n\n"
        "def call() -> None:\n"
        "    subprocess = object()\n"
        "    subprocess.run_checked()\n",
    )
    candidate = _graph(
        candidate_root,
        target="run_checked",
        include_edge=False,
        committed=False,
    )

    check = check_rename_obligations(
        root=candidate_root,
        graph=candidate,
        obligations=obligations,
    )

    assert not check.passed
    assert check.transitions[0].status == "analysis_unresolved"
    assert "target alias 'subprocess' rebound" in check.unresolved[0]


@pytest.mark.unit
@pytest.mark.domain_protocol
def test_unrelated_local_alias_does_not_block_governed_caller(tmp_path: Path) -> None:
    """Keep an unrelated function's local name outside the caller's binding state."""
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"
    obligations = compile_rename_obligations(
        root=baseline_root,
        graph=_baseline(baseline_root),
        spec=_SPEC,
    )
    _write(
        candidate_root,
        "src/viper/_subprocess.py",
        "def run_checked() -> None:\n    pass\n",
    )
    _write(
        candidate_root,
        "tests/test_use.py",
        "from viper import _subprocess as subprocess\n\n"
        "def call() -> None:\n"
        "    subprocess.run_checked()\n\n"
        "def unrelated() -> object:\n"
        "    subprocess = object()\n"
        "    return subprocess\n",
    )
    candidate = _graph(
        candidate_root,
        target="run_checked",
        include_edge=True,
        committed=False,
    )

    check = check_rename_obligations(
        root=candidate_root,
        graph=candidate,
        obligations=obligations,
    )

    assert check.passed
    assert check.unresolved == ()


@pytest.mark.unit
@pytest.mark.domain_protocol
def test_changed_source_bytes_reject_stale_graph(tmp_path: Path) -> None:
    """Reject a graph whose snapshot no longer matches the scanned files."""
    root = tmp_path / "baseline"
    graph = _baseline(root)
    _write(root, "tests/test_use.py", "def call() -> None:\n    pass\n")

    with pytest.raises(
        RenameAnalysisError,
        match="SourceGraph snapshot differs from scanned source",
    ):
        compile_rename_obligations(root=root, graph=graph, spec=_SPEC)
