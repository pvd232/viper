"""Verify the source graph preserves the Python relationships used by planning."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from viper import scheduling
from viper._contract_traceability import ContractTarget, RepoSymbolRef
from viper._subprocess import run as run_subprocess
from viper._system_impact.codeql import (
    _qualified_declarations,
    _tree_digest,
    analyze_source,
    lowering_digest,
    source_digest,
)
from viper._system_impact.source import extract_declaration_bytes
from viper.system_impact.check import _one_hop
from viper.system_impact.models import (
    CodeQLExtractionSpec,
    CodeQLQuerySpec,
    ResolvedContractTarget,
    SourceEdge,
    SourceGraph,
    SourceGraphFormat,
    SourceNode,
    SourceSnapshot,
)

_REVISION = "1" * 40


def _sha256(value: bytes) -> str:
    """Hash fixture bytes."""
    return hashlib.sha256(value).hexdigest()


def _node(path: str, symbol: str) -> SourceNode:
    """Build one valid node for the one-hop test."""
    column = int(_sha256(f"{path}:{symbol}".encode())[:8], 16)
    return SourceNode(
        node_id=f"{path}:{symbol}",
        path=path,
        symbol=symbol,
        kind="function",
        binding_start_line=1,
        binding_start_col=column,
        binding_end_line=1,
        binding_end_col=column + 1,
        start_line=1,
        start_col=column,
        end_line=1,
        end_col=column + 1,
        sha256="f" * 64,
    )


def test_conditional_declarations_use_one_shared_walk() -> None:
    """Resolve declarations nested under module and class control flow."""
    source = (
        b"if ENABLED:\n"
        b"    def load() -> int:\n"
        b"        return 1\n"
        b"\n"
        b"class Worker:\n"
        b"    if ENABLED:\n"
        b"        def run(self) -> int:\n"
        b"            return 1\n"
    )
    symbols = {
        declaration.symbol for declaration in _qualified_declarations(ast.parse(source))
    }

    assert {"load", "Worker", "Worker.run"} <= symbols
    assert extract_declaration_bytes(source, "load").startswith(b"def load")
    assert extract_declaration_bytes(source, "Worker.run").startswith(b"def run")


def test_dotted_imports_use_the_full_contract_target_identity() -> None:
    """Keep graph and scheduler identity aligned for an unaliased dotted import."""
    source = b"import urllib.parse\n"

    assert scheduling._imports(source) == {"urllib.parse"}
    assert scheduling._drop_import(source, "urllib.parse") == b""


def test_added_target_collects_candidate_neighbors() -> None:
    """Include every candidate edge kind around a newly added declaration."""
    target = _node("src/api.py", "new_api")
    caller = _node("src/caller.py", "call_api")
    edge = SourceEdge(
        edge_id="1" * 64,
        source=caller.node_id,
        target=target.node_id,
        kind="calls",
        query="viper/python-impact/dependencies",
        path=caller.path,
        line=1,
    )
    contract_target = ContractTarget.model_construct(
        requirements=("CQA-01",),
        block_id="P0-CQA-01",
        action="add",
        target=RepoSymbolRef(path=target.path, symbol=target.symbol),
        declaration=None,
    )
    resolved = ResolvedContractTarget.model_construct(
        target=contract_target,
        baseline_node=None,
        baseline_sha256=None,
        expected_sha256=target.sha256,
        change_kind="added",
    )
    baseline = SourceGraph.model_construct(nodes=(caller,), edges=())
    realized = SourceGraph.model_construct(nodes=(caller, target), edges=(edge,))

    impact = _one_hop(
        targets=(resolved,),
        baseline=baseline,
        realized=realized,
    )

    assert impact.targets == (target.node_id,)
    assert impact.neighbors == (caller.node_id,)
    assert impact.after == (edge.edge_id,)
    assert impact.added == (edge.edge_id,)


@pytest.mark.integration
def test_codeql_distinguishes_attribute_reads_and_writes(tmp_path: Path) -> None:
    """Prove reads, writes, and augmented assignments with the checked-in pack."""
    if os.environ.get("VIPER_RUN_CODEQL_TESTS") != "1":
        pytest.skip("set VIPER_RUN_CODEQL_TESTS=1 to run the real CodeQL check")

    executable_value = os.environ.get("VIPER_CODEQL") or shutil.which("codeql")
    assert executable_value is not None, "CodeQL is unavailable"
    executable = Path(executable_value).resolve()
    pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    installed = run_subprocess(
        (str(executable), "pack", "install", str(pack)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    version = run_subprocess(
        (str(executable), "version", "--format=json"),
        check=True,
        capture_output=True,
        text=True,
    )
    languages = run_subprocess(
        (str(executable), "resolve", "languages", "--format=json"),
        check=True,
        capture_output=True,
        text=True,
    )

    root = tmp_path / "source"
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "if True:\n"
        "    def conditional() -> int:\n"
        "        return 1\n"
        "\n"
        "class Counter:\n"
        "    value = 0\n"
        "\n"
        "    if True:\n"
        "        def read(self) -> int:\n"
        "            return self.value\n"
        "\n"
        "        def update(self, value: int) -> None:\n"
        "            self.value = value\n"
        "\n"
        "        def increment(self) -> None:\n"
        "            self.value += 1\n"
        "\n"
        "def freeze_artifact(value: int) -> int:\n"
        "    return value\n"
        "\n"
        "def freeze_stage(values: list[int]) -> dict[int, int]:\n"
        "    return {value: freeze_artifact(value) for value in values}\n",
        encoding="utf-8",
    )
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    extraction = CodeQLExtractionSpec(
        version=json.loads(version.stdout)["version"],
        platform=sys.platform,
        executable_sha256=_sha256(executable.read_bytes()),
        extractor_sha256=_tree_digest(
            Path(json.loads(languages.stdout)["python"][0]).resolve()
        ),
    )
    query = CodeQLQuerySpec(
        pack="viper/python-impact@1.1.0",
        pack_sha256=_tree_digest(pack),
        suite="source-facts.qls",
    )
    format = SourceGraphFormat(
        schema_version=3,
        lowering_sha256=lowering_digest(),
    )

    graph = analyze_source(
        root,
        snapshot=snapshot,
        extraction=extraction,
        query=query,
        format=format,
        codeql_executable=executable,
        query_pack=pack,
        cache_root=tmp_path / "cache",
        artifact_root=tmp_path / "artifacts",
    )

    symbols = {node.symbol for node in graph.nodes}
    assert {
        "conditional",
        "Counter.read",
        "Counter.update",
        "Counter.increment",
    } <= symbols
    relationships = [
        (edge.source, edge.kind, edge.target)
        for edge in graph.edges
        if edge.target == "src/example.py:Counter.value"
    ]
    assert (
        relationships.count(
            ("src/example.py:Counter.read", "reads", "src/example.py:Counter.value")
        )
        == 1
    )
    assert any(
        edge.source == "src/example.py:freeze_stage"
        and edge.kind == "calls"
        and edge.target == "src/example.py:freeze_artifact"
        for edge in graph.edges
    )
    assert (
        relationships.count(
            ("src/example.py:Counter.read", "writes", "src/example.py:Counter.value")
        )
        == 0
    )
    assert (
        relationships.count(
            ("src/example.py:Counter.update", "reads", "src/example.py:Counter.value")
        )
        == 0
    )
    assert (
        relationships.count(
            ("src/example.py:Counter.update", "writes", "src/example.py:Counter.value")
        )
        == 1
    )
    assert (
        relationships.count(
            (
                "src/example.py:Counter.increment",
                "reads",
                "src/example.py:Counter.value",
            )
        )
        == 1
    )
    assert (
        relationships.count(
            (
                "src/example.py:Counter.increment",
                "writes",
                "src/example.py:Counter.value",
            )
        )
        == 1
    )
