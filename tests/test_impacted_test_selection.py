"""Verify declaration-linked test selection from CodeQL/AST source graphs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.select_impacted_tests import (
    ImpactSelectionError,
    select_impacted_tests,
    source_digest,
)


def _node(node_id: str, *, kind: str = "function") -> dict[str, object]:
    """Create one source node with the AST binding fields consumed by selection."""
    path, symbol = node_id.split(":", 1)
    return {
        "node_id": node_id,
        "path": path,
        "symbol": symbol,
        "kind": kind,
        "binding_start_line": 7,
        "binding_start_col": 4,
    }


@pytest.fixture
def impact_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Write one source graph and its declaration-observer manifest."""
    target = "src/viper/storage.py:LocalArtifactStore"
    caller = "src/viper/authoring.py:_freeze_input"
    test = "tests/test_storage.py:test_store_identity"
    source_root = tmp_path / "source"
    for relative in (
        "src/viper/storage.py",
        "src/viper/authoring.py",
        "tests/test_storage.py",
    ):
        source = source_root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"# {relative}\n", encoding="utf-8")
    graph = tmp_path / "source-graph.json"
    graph.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "snapshot": {"source_sha256": source_digest(source_root)},
                "nodes": [_node(target), _node(caller), _node(test)],
                "edges": [
                    {"source": caller, "target": target, "kind": "constructs"},
                    {"source": test, "target": target, "kind": "calls"},
                ],
            }
        ),
        encoding="utf-8",
    )
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
    return graph, observers, source_root


def test_selects_target_observers_and_one_hop_test_declarations(
    impact_files: tuple[Path, Path, Path],
) -> None:
    """Select declared observers plus a test directly connected by CodeQL."""
    graph, observers, source_root = impact_files
    result = select_impacted_tests(
        graph_path=graph,
        source_root=source_root,
        observer_path=observers,
        declarations=("src/viper/storage.py:LocalArtifactStore",),
    )

    assert result["mode"] == "nodeids"
    assert result["selected_tests"] == [
        "tests/test_prior_run_inputs.py::test_caller",
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]
    assert result["pytest_args"] == result["selected_tests"]
    assert result["target_ast_bindings"] == [
        {
            "node_id": "src/viper/storage.py:LocalArtifactStore",
            "path": "src/viper/storage.py",
            "symbol": "LocalArtifactStore",
            "line": 7,
            "byte_column": 4,
        }
    ]


def test_unmapped_neighbor_widens_to_the_target_domain(
    impact_files: tuple[Path, Path, Path],
) -> None:
    """Run the domain when a production neighbor has no observer declaration."""
    graph, observers, source_root = impact_files
    text = observers.read_text(encoding="utf-8")
    observers.write_text(text.rsplit("\n[[declarations]]\n", 1)[0], encoding="utf-8")

    result = select_impacted_tests(
        graph_path=graph,
        source_root=source_root,
        observer_path=observers,
        declarations=("src/viper/storage.py:LocalArtifactStore",),
    )

    assert result["mode"] == "domain"
    assert result["fallback_domains"] == ["domain_authoring"]
    assert result["pytest_args"] == [
        "tests",
        "-m",
        "(domain_authoring) and (unit or contract)",
    ]
    assert result["incomplete_declarations"] == ["src/viper/authoring.py:_freeze_input"]


def test_unmapped_neighbor_uses_its_graph_linked_observing_test(
    impact_files: tuple[Path, Path, Path],
) -> None:
    """Select a test reached through an impacted production declaration."""
    graph, observers, source_root = impact_files
    text = observers.read_text(encoding="utf-8")
    observers.write_text(text.rsplit("\n[[declarations]]\n", 1)[0], encoding="utf-8")
    payload = json.loads(graph.read_text(encoding="utf-8"))
    payload["edges"].append(
        {
            "source": "tests/test_storage.py:test_store_identity",
            "target": "src/viper/authoring.py:_freeze_input",
            "kind": "calls",
        }
    )
    graph.write_text(json.dumps(payload), encoding="utf-8")

    result = select_impacted_tests(
        graph_path=graph,
        source_root=source_root,
        observer_path=observers,
        declarations=("src/viper/storage.py:LocalArtifactStore",),
    )

    assert result["mode"] == "nodeids"
    assert result["fallback_domains"] == []
    assert result["pytest_args"] == [
        "tests/test_storage.py::test_direct",
        "tests/test_storage.py::test_store_identity",
    ]


def test_absent_target_without_a_declaration_map_runs_the_repository(
    impact_files: tuple[Path, Path, Path],
) -> None:
    """Run every fast test when neither the graph nor manifest owns a target."""
    graph, observers, source_root = impact_files
    result = select_impacted_tests(
        graph_path=graph,
        source_root=source_root,
        observer_path=observers,
        declarations=("src/viper/missing.py:missing",),
    )

    assert result["mode"] == "fast_repository"
    assert result["pytest_args"] == ["tests", "-m", "unit or contract"]


def test_rejects_an_edge_without_both_ast_nodes(
    impact_files: tuple[Path, Path, Path],
) -> None:
    """Reject a resolver graph whose edge cannot reach an AST declaration."""
    graph, observers, source_root = impact_files
    payload = json.loads(graph.read_text(encoding="utf-8"))
    payload["nodes"] = payload["nodes"][:-1]
    graph.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ImpactSelectionError, match="absent node"):
        select_impacted_tests(
            graph_path=graph,
            source_root=source_root,
            observer_path=observers,
            declarations=("src/viper/storage.py:LocalArtifactStore",),
        )


def test_rejects_a_graph_for_different_source_bytes(
    impact_files: tuple[Path, Path, Path],
) -> None:
    """Reject cached dependency facts after the analyzed source changes."""
    graph, observers, source_root = impact_files
    (source_root / "src/viper/storage.py").write_text("CHANGED = True\n")

    with pytest.raises(ImpactSelectionError, match="current source"):
        select_impacted_tests(
            graph_path=graph,
            source_root=source_root,
            observer_path=observers,
            declarations=("src/viper/storage.py:LocalArtifactStore",),
        )
