"""Verify staged CodeQL analysis and independent cache keys."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import viper._system_impact.codeql as codeql
from tools.plan import check as preflight
from viper._system_impact.codeql import (
    CodeQLAnalysisError,
    _tree_digest,
    analyze_source,
    lowering_digest,
    source_digest,
)
from viper.system_impact.models import (
    CodeQLExtractionSpec,
    CodeQLQuerySpec,
    SourceGraphFormat,
    SourceSnapshot,
    stage_key,
)

_REVISION = "1" * 40


def _sha256(value: bytes) -> str:
    """Hash bytes used by a test fixture."""
    return hashlib.sha256(value).hexdigest()


def _write_fake_codeql(path: Path, extractor: Path, calls: Path) -> Path:
    """Write a process-compatible CodeQL stand-in for all three stages."""
    extractor.mkdir()
    (extractor / "extractor.py").write_text("VERSION = 1\n", encoding="utf-8")
    source = f"""#!{sys.executable}
import json
import sys
from pathlib import Path

args = sys.argv[1:]
calls = Path({str(calls)!r})
with calls.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")

def option(prefix: str) -> str:
    return next(value.split("=", 1)[1] for value in args if value.startswith(prefix))

if args[0] == "version":
    print(json.dumps({{"version": "2.26.4"}}))
elif args[:2] == ["resolve", "languages"]:
    print(json.dumps({{"python": [{str(extractor)!r}]}}))
elif args[:2] == ["database", "create"]:
    database = Path(args[2])
    facts = database / "db-python/default"
    facts.mkdir(parents=True)
    (facts / "facts.rel").write_text("facts", encoding="utf-8")
    (database / "src.zip").write_bytes(b"source")
elif args[:2] == ["database", "run-queries"]:
    database = Path(args[3])
    results = database / "results/viper/python-impact"
    results.mkdir(parents=True)
    (results / "Declarations.bqrs").write_text("Declarations", encoding="utf-8")
    (results / "Dependencies.bqrs").write_text("Dependencies", encoding="utf-8")
    cache = database / "db-python/default/cache"
    cache.mkdir()
    (cache / "query.cache").write_text("mutable", encoding="utf-8")
elif args[:2] == ["bqrs", "decode"]:
    query = Path(args[2]).read_text(encoding="utf-8")
    rows = (
        [
            ["src/example.py", "dependency", "function", 1, 1],
            ["src/example.py", "dependent", "function", 4, 1],
        ]
        if query == "Declarations"
        else [["src/example.py", 4, 1, "src/example.py", 1, 1,
               "calls", "src/example.py", 5]]
    )
    Path(option("--output=")).write_text(
        json.dumps({{"#select": {{"tuples": rows}}}}),
        encoding="utf-8",
    )
else:
    raise SystemExit(2)
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_source(root: Path) -> None:
    """Write two declarations joined by one call."""
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def dependency() -> int:\n"
        "    return 1\n"
        "\n"
        "def dependent() -> int:\n"
        "    return dependency()\n",
        encoding="utf-8",
    )


def _specs(
    executable: Path,
    extractor: Path,
    query_pack: Path,
) -> tuple[CodeQLExtractionSpec, CodeQLQuerySpec, SourceGraphFormat]:
    """Build the three independent specifications used by the fixture."""
    return (
        CodeQLExtractionSpec(
            version="2.26.4",
            platform="test",
            executable_sha256=_sha256(executable.read_bytes()),
            extractor_sha256=_tree_digest(extractor),
        ),
        CodeQLQuerySpec(
            pack="viper/python-impact@1.1.0",
            pack_sha256=_tree_digest(query_pack),
            suite="source-facts.qls",
        ),
        SourceGraphFormat(
            schema_version=3,
            lowering_sha256=lowering_digest(),
        ),
    )


def test_analysis_uses_three_keys_and_runs_the_suite_once(tmp_path: Path) -> None:
    """Reuse extraction, query, and graph results under their own keys."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "query": query,
        "format": format,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
    }

    first = analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-first",
    )
    second = analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-second",
    )

    assert first == second
    assert first.receipt.database.key == stage_key(snapshot, extraction)
    assert first.receipt.query.key == stage_key(
        first.receipt.database.key,
        first.receipt.database.sha256,
        query,
    )
    assert first.receipt.graph.key == stage_key(
        first.receipt.query.key,
        first.receipt.query.sha256,
        format,
    )
    for receipt in (
        first.receipt.database,
        first.receipt.query,
        first.receipt.graph,
    ):
        assert receipt.exit_code == 0
        failed = receipt.model_dump(mode="json")
        failed["exit_code"] = 1
        with pytest.raises(ValueError):
            type(receipt).model_validate(failed)
        wrong_key = receipt.model_dump(mode="json")
        wrong_key["key"] = "0" * 64
        with pytest.raises(ValueError, match="key differs"):
            type(receipt).model_validate(wrong_key)
    assert tuple(node.symbol for node in first.nodes) == ("dependency", "dependent")
    assert tuple(edge.kind for edge in first.edges) == ("calls",)
    assert (tmp_path / "artifacts-second/Declarations.json").is_file()
    assert (tmp_path / "artifacts-second/Dependencies.json").is_file()
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert sum(command[:2] == ["database", "create"] for command in commands) == 1
    assert sum(command[:2] == ["database", "run-queries"] for command in commands) == 1


def test_analysis_rejects_each_stage_identity_drift(tmp_path: Path) -> None:
    """Reject source, extractor, and query-pack bytes outside the plan."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "query": query,
        "format": format,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
        "artifact_root": tmp_path / "artifacts",
    }

    with pytest.raises(CodeQLAnalysisError, match="source bytes"):
        analyze_source(
            **{
                **arguments,
                "snapshot": snapshot.model_copy(update={"source_sha256": "0" * 64}),
            }
        )
    with pytest.raises(CodeQLAnalysisError, match="extractor digest"):
        analyze_source(
            **{
                **arguments,
                "extraction": extraction.model_copy(
                    update={"extractor_sha256": "0" * 64}
                ),
            }
        )
    with pytest.raises(CodeQLAnalysisError, match="query-pack digest"):
        analyze_source(
            **{
                **arguments,
                "query": query.model_copy(update={"pack_sha256": "0" * 64}),
            }
        )


def test_query_change_reuses_extraction(tmp_path: Path) -> None:
    """Reuse the database and rerun only queries and lowering."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = tmp_path / "query-pack"
    shutil.copytree(
        Path(__file__).parents[1] / "tools/codeql/viper-python-impact",
        query_pack,
    )
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    common = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "format": format,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
    }
    first = analyze_source(
        **common,
        query=query,
        artifact_root=tmp_path / "artifacts-first",
    )
    (query_pack / "revision.txt").write_text("second", encoding="utf-8")
    changed_query = query.model_copy(update={"pack_sha256": _tree_digest(query_pack)})
    second = analyze_source(
        **common,
        query=changed_query,
        artifact_root=tmp_path / "artifacts-second",
    )

    assert first.receipt.database == second.receipt.database
    assert first.receipt.query != second.receipt.query
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert sum(command[:2] == ["database", "create"] for command in commands) == 1
    assert sum(command[:2] == ["database", "run-queries"] for command in commands) == 2


def test_format_change_reuses_database_and_bqrs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rerun lowering without repeating extraction or query execution."""
    asset = tmp_path / "lowering.py"
    asset.write_text("VERSION = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        codeql,
        "_LOWERING_ASSETS",
        (("src/viper/lowering.py", asset),),
    )
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    common = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "query": query,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
    }
    first = analyze_source(
        **common,
        format=format,
        artifact_root=tmp_path / "artifacts-first",
    )
    asset.write_text("VERSION = 2\n", encoding="utf-8")
    changed_format = SourceGraphFormat(
        schema_version=3,
        lowering_sha256=lowering_digest(),
    )
    second = analyze_source(
        **common,
        format=changed_format,
        artifact_root=tmp_path / "artifacts-second",
    )

    assert first.receipt.database == second.receipt.database
    assert first.receipt.query == second.receipt.query
    assert first.receipt.graph != second.receipt.graph
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert sum(command[:2] == ["database", "create"] for command in commands) == 1
    assert sum(command[:2] == ["database", "run-queries"] for command in commands) == 1
    assert sum(command[:2] == ["bqrs", "decode"] for command in commands) == 4


def test_tampered_graph_cache_rebuilds(tmp_path: Path) -> None:
    """Reject a cached graph whose receipt no longer recomputes."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "query": query,
        "format": format,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
    }
    analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-first",
    )
    graph_path = next((tmp_path / "cache/graphs").glob("*/source-graph.json"))
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    payload["receipt"]["query"]["key"] = "0" * 64
    payload["receipt"]["graph"]["query_key"] = "0" * 64
    graph_path.write_text(json.dumps(payload), encoding="utf-8")

    rebuilt = analyze_source(
        **arguments,
        artifact_root=tmp_path / "artifacts-second",
    )

    assert rebuilt.receipt.query.key != "0" * 64
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert sum(command[:2] == ["database", "create"] for command in commands) == 1
    assert sum(command[:2] == ["database", "run-queries"] for command in commands) == 1
    assert sum(command[:2] == ["bqrs", "decode"] for command in commands) == 4


def test_lowering_digest_must_match_loaded_assets(tmp_path: Path) -> None:
    """Reject a caller-supplied graph-format digest."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, _format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )

    with pytest.raises(CodeQLAnalysisError, match="lowering digest"):
        analyze_source(
            root,
            snapshot=snapshot,
            extraction=extraction,
            query=query,
            format=SourceGraphFormat(
                schema_version=3,
                lowering_sha256="0" * 64,
            ),
            codeql_executable=executable,
            query_pack=query_pack,
            cache_root=tmp_path / "cache",
            artifact_root=tmp_path / "artifacts",
        )


def test_candidate_pythonpath_spans_plan_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep candidate imports active through the behavioral gates, then restore them."""
    tree = ast.parse(inspect.getsource(preflight.validate))
    scopes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "_environment"
            and any(
                keyword.arg == "PYTHONPATH" for keyword in item.context_expr.keywords
            )
            for item in node.items
        )
    ]
    assert len(scopes) == 1
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "check_plan"
        for statement in scopes[0].body
        for node in ast.walk(statement)
    )

    monkeypatch.setenv("PYTHONPATH", "before")
    with preflight._environment(PYTHONPATH="candidate"):
        assert os.environ["PYTHONPATH"] == "candidate"
    assert os.environ["PYTHONPATH"] == "before"


def test_cached_graph_reuse_decodes_only_requested_artifacts(tmp_path: Path) -> None:
    """Enforce codeql.graph.warm_reuse and explicit evidence materialization."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "query": query,
        "format": format,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
    }

    first = analyze_source(**arguments)
    after_miss = [json.loads(line) for line in calls.read_text().splitlines()]
    second = analyze_source(**arguments)
    after_reuse = [json.loads(line) for line in calls.read_text().splitlines()]

    assert first == second
    assert sum(command[:2] == ["bqrs", "decode"] for command in after_miss) == 2
    assert sum(command[:2] == ["bqrs", "decode"] for command in after_reuse) == 2

    artifact_root = tmp_path / "artifacts"
    third = analyze_source(**arguments, artifact_root=artifact_root)
    after_evidence = [json.loads(line) for line in calls.read_text().splitlines()]

    assert third == first
    assert sum(command[:2] == ["bqrs", "decode"] for command in after_evidence) == 4
    assert {path.name for path in artifact_root.iterdir()} == {
        "Declarations.bqrs",
        "Declarations.json",
        "Dependencies.bqrs",
        "Dependencies.json",
    }


def test_requested_artifacts_reject_decode_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enforce codeql.evidence.requested when a cached graph cannot be decoded."""
    root = tmp_path / "source"
    _write_source(root)
    query_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    calls = tmp_path / "calls.jsonl"
    extractor = tmp_path / "extractor"
    executable = _write_fake_codeql(tmp_path / "codeql", extractor, calls)
    extraction, query, format = _specs(executable, extractor, query_pack)
    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    arguments = {
        "snapshot_root": root,
        "snapshot": snapshot,
        "extraction": extraction,
        "query": query,
        "format": format,
        "codeql_executable": executable,
        "query_pack": query_pack,
        "cache_root": tmp_path / "cache",
    }
    analyze_source(**arguments)
    original_run = codeql._run

    def fail_decode(
        command: tuple[str, ...],
        *,
        cwd: Path,
    ) -> tuple[bytes, bytes]:
        if command[1:3] == ("bqrs", "decode"):
            raise CodeQLAnalysisError(
                "CodeQL command failed (bqrs decode): forced failure"
            )
        return original_run(command, cwd=cwd)

    monkeypatch.setattr(codeql, "_run", fail_decode)
    artifact_root = tmp_path / "artifacts"
    with pytest.raises(CodeQLAnalysisError, match="CodeQL command failed"):
        analyze_source(**arguments, artifact_root=artifact_root)
    assert not artifact_root.exists()
