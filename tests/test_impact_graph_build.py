"""Guard VIPER's thin adapter to the independently installed graph builder."""

from pathlib import Path

import pytest

from tools.build_test_impact_graph import build_graph


def test_graph_builder_uses_shared_owner_with_explicit_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve caller inputs without a historical checkout or source patch."""
    received: list[dict[str, object]] = []

    def capture(**kwargs: object) -> None:
        """Record the one shared operation at the adapter boundary."""
        received.append(kwargs)

    monkeypatch.setattr("source_impact.build.build_graph", capture)
    build_graph(
        repository=tmp_path,
        codeql=tmp_path / "codeql",
        cache=tmp_path / "cache",
        output=tmp_path / "graph.json",
        analyzed_roots=("contract_protocol", "tests"),
    )
    assert received == [
        {
            "repository": tmp_path,
            "codeql_executable": tmp_path / "codeql",
            "cache": tmp_path / "cache",
            "output": tmp_path / "graph.json",
            "analyzed_roots": ("contract_protocol", "tests"),
        }
    ]


def test_shared_builder_failure_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Let validation failures stop the command before a graph is advertised."""

    def fail(**kwargs: object) -> None:
        """Model an invalid source inventory from the shared owner."""
        del kwargs
        raise ValueError("source inventory changed")

    monkeypatch.setattr("source_impact.build.build_graph", fail)
    with pytest.raises(ValueError, match="source inventory changed"):
        build_graph(
            repository=tmp_path,
            codeql=tmp_path / "codeql",
            cache=tmp_path / "cache",
            output=tmp_path / "graph.json",
        )
