"""Verify the unittest adapter for repository-neutral impact selection."""

from __future__ import annotations

import json
from pathlib import Path

from tools.select_impacted_tests import source_digest
from tools.select_unittest_tests import select_unittest_tests

ANALYZED_ROOTS = frozenset({"contract_protocol", "tests"})


def _write_graph(root: Path, graph: Path) -> None:
    """Write one current graph linking production code to a unittest method."""
    production = root / "contract_protocol" / "compiler.py"
    test = root / "tests" / "contract_protocol" / "test_compiler.py"
    production.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    production.write_text("def compile_state():\n    pass\n", encoding="utf-8")
    test.write_text(
        "class CompilerTests:\n    def test_compile_state(self):\n        pass\n",
        encoding="utf-8",
    )
    graph.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "snapshot": {
                    "source_sha256": source_digest(root, ANALYZED_ROOTS),
                },
                "nodes": [
                    {
                        "node_id": "contract_protocol/compiler.py:compile_state",
                        "path": "contract_protocol/compiler.py",
                        "symbol": "compile_state",
                        "binding_start_line": 1,
                        "binding_start_col": 4,
                    },
                    {
                        "node_id": (
                            "tests/contract_protocol/test_compiler.py:"
                            "CompilerTests.test_compile_state"
                        ),
                        "path": "tests/contract_protocol/test_compiler.py",
                        "symbol": "CompilerTests.test_compile_state",
                        "binding_start_line": 2,
                        "binding_start_col": 8,
                    },
                ],
                "edges": [
                    {
                        "source": (
                            "tests/contract_protocol/test_compiler.py:"
                            "CompilerTests.test_compile_state"
                        ),
                        "target": "contract_protocol/compiler.py:compile_state",
                        "kind": "calls",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_returns_importable_unittest_name(tmp_path: Path) -> None:
    """Convert a graph-reachable test method into its unittest name."""
    graph = tmp_path / "graph.json"
    _write_graph(tmp_path, graph)

    result = select_unittest_tests(
        graph_path=graph,
        source_root=tmp_path,
        declarations=("contract_protocol/compiler.py:compile_state",),
        analyzed_roots=ANALYZED_ROOTS,
        fallback="tests.contract_protocol",
    )

    assert result["mode"] == "tests"
    assert result["unittest_args"] == (
        "tests.contract_protocol.test_compiler.CompilerTests.test_compile_state",
    )


def test_uses_fallback_for_unresolved_declaration(tmp_path: Path) -> None:
    """Return the declared suite when the graph reaches no test."""
    graph = tmp_path / "graph.json"
    _write_graph(tmp_path, graph)

    result = select_unittest_tests(
        graph_path=graph,
        source_root=tmp_path,
        declarations=("contract_protocol/compiler.py:missing",),
        analyzed_roots=ANALYZED_ROOTS,
        fallback="tests.contract_protocol",
    )

    assert result["mode"] == "fallback"
    assert result["unittest_args"] == ("tests.contract_protocol",)
