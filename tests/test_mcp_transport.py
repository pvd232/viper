"""Exercise discovery and tool calls through the installed MCP stdio client."""

import hashlib
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from mcp import types
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError

from tests._documentation import python_blocks
from viper import _subprocess as subprocess
from viper.catalog import catalog
from viper.journal import DurableJournal
from viper.journals import encode_journal, parse_journal
from viper.knowledge import (
    JournalAssertion,
    JournalVectorView,
    KnowledgeRecordEnvelope,
    KnowledgeVector,
    OntologySpec,
    PrimitiveSpec,
)
from viper.mcp import call_tool, get_prompt, prompt_registry, tool_registry
from viper.references import LocalFileRef
from viper.reuse import StageReuseCandidate
from viper.serialization import parse_yaml_bytes
from viper.storage import local_artifact_store


def test_documented_mcp_client_uses_the_live_stdio_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Execute the printed read-only client against a real workspace server."""
    source_root = Path(__file__).parents[1]
    program = python_blocks((source_root / "docs/reference/agents.md").read_text())[0]
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    subprocess.run(("git", "init", "--quiet", str(root)), check=True)
    catalog(root=root).refresh()
    monkeypatch.chdir(root)
    exec(compile(program, "documented_mcp_client", "exec"), {"__name__": "__main__"})
    output = capsys.readouterr().out
    assert "schema: RunSpec" in output
    assert "indexed successful runs: 0" in output
    assert "next cursor: None" in output


@pytest.mark.parametrize("access", ("read", "execute"))
def test_stdio_discovery_and_calls_use_the_server_workspace(
    tmp_path: Path, access: str
) -> None:
    """Use a real subprocess from another directory, including failed requests."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    subprocess.run(("git", "init", "--quiet", str(root)), check=True)
    catalog(root=root).refresh()
    DurableJournal(root / "attempt.jsonl").append(
        "allocated", "attempt allocated", recorded_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    async def exercise() -> None:
        """Discover the server and check structured responses over its transport."""
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "viper.mcp", "--root", str(root), "--access", access],
            cwd=tmp_path,
        )
        async with Client(server, read_timeout_seconds=30) as client:
            tools = (await client.list_tools()).tools
            names = {tool.name for tool in tools}
            assert ("run" in names) == (access == "execute")
            capabilities = await client.call_tool("get_capabilities", {})
            assert set(capabilities.structured_content["operations"]) == names
            schema = await client.call_tool("get_schema", {"name": "RunSpec"})
            assert schema.structured_content["json_schema"]["title"] == "RunSpec"
            status = await client.call_tool("status", {"path": "attempt.jsonl"})
            assert status.structured_content["state"] == "allocated"
            assert status.structured_content["path"] == str(root / "attempt.jsonl")
            search = await client.call_tool("search_runs", {"query": {"limit": 2}})
            assert search.structured_content["page"]["items"] == []
            for name, arguments in (
                ("get_schema", {"name": "MissingSchema"}),
                ("get_schema", {}),
                ("status", {"path": "../outside"}),
                ("search_runs", {"root": str(tmp_path), "query": {}}),
            ):
                result = await client.call_tool(name, arguments)
                assert result.is_error
                assert result.structured_content["status"] == "error"
                assert isinstance(result.content[0], types.TextContent)
                assert json.loads(result.content[0].text) == result.structured_content
            resources = (await client.list_resources()).resources
            assert "viper://guide" in {str(item.uri) for item in resources}
            for resource in resources:
                assert (await client.read_resource(str(resource.uri))).contents
            with pytest.raises(MCPError, match="unknown VIPER resource"):
                await client.read_resource("viper://run/missing")
            templates = (await client.list_resource_templates()).resource_templates
            assert {item.name for item in templates} == {"run", "benchmark", "evidence"}
            for prompt in (await client.list_prompts()).prompts:
                arguments = {
                    item.name: "attempt.jsonl" for item in (prompt.arguments or [])
                }
                assert (await client.get_prompt(prompt.name, arguments)).messages
            with pytest.raises(MCPError, match="requires exactly"):
                await client.get_prompt("compare_runs", {})
            if access == "read":
                with pytest.raises(MCPError, match="unavailable"):
                    await client.call_tool("run", {})
            else:
                refreshed = await client.call_tool("knowledge_refresh", {})
                assert not refreshed.is_error
                assert refreshed.structured_content["status"] == "ok"

    anyio.run(exercise)


def test_mcp_rejects_symlink_escape_and_disallowed_tools(tmp_path: Path) -> None:
    """Reject filesystem escapes and execute calls even when tools/list is bypassed."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    result = call_tool(root, "read", "status", {"path": "outside/attempt.jsonl"})
    assert result.is_error
    assert result.structured_content["code"] == "invalid_request"
    with pytest.raises(ValueError, match="unavailable"):
        call_tool(root, "read", "run", {})


def test_mcp_prompts_require_task_specific_inputs() -> None:
    """Reject missing prompt arguments and retain concrete tool instructions."""
    for prompt in prompt_registry():
        with pytest.raises(ValueError, match="requires exactly"):
            get_prompt(prompt.name, {})
    prompt = get_prompt(
        "compare_runs", {"left_path": "left.yaml", "right_path": "right.yaml"}
    )
    assert isinstance(prompt.messages[0].content, types.TextContent)
    assert "compare_runs" in prompt.messages[0].content.text
    tools = {tool.name: tool for tool in tool_registry()}
    assert tools["verify_run"].annotations is not None
    assert tools["get_schema"].annotations is not None
    assert tools["verify_run"].annotations.open_world_hint
    assert not tools["get_schema"].annotations.open_world_hint


@pytest.mark.parametrize(
    "refresh_knowledge,journal", ((False, False), (True, False), (False, True))
)
def test_stdio_executes_a_saved_training_plan(
    tmp_path: Path, refresh_knowledge: bool, journal: bool
) -> None:
    """Execute training through MCP and retain its index during knowledge refresh."""
    root = tmp_path / "workspace"
    source_root = Path(__file__).parents[1]
    shutil.copytree(
        source_root / "examples",
        root / "examples",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(source_root / "pyproject.toml", root / "pyproject.toml")
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    journal_raw = (
        "## Observations\r\nMetric: mean_squared_error\r\nStage: train\r\n"
        "Epoch: 20\r\nThe saved α-model reached a finite loss.\r\n"
    ).encode()
    if journal:
        journal_path = root / "experiments/cpu_quickstart/JOURNAL.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_bytes(journal_raw)
    for command in (
        ("init", "--quiet"),
        ("remote", "add", "origin", "https://github.com/example/workspace"),
        ("add", "."),
        (
            "-c",
            "user.name=VIPER tests",
            "-c",
            "user.email=viper@example.com",
            "commit",
            "--quiet",
            "-m",
            "Training fixture",
        ),
    ):
        subprocess.run(("git", "-C", str(root), *command), check=True)
    # Load callables from the committed fixture, preserving their source paths.
    preparation = subprocess.run(
        (
            sys.executable,
            "-c",
            """
import json
from pathlib import Path
from examples.cpu_quickstart import study
from viper.authoring import freeze_run_plan, plan
from viper.references import GitFileRef
from viper.repository import read_source
from viper.runtime import LocalEnvSpec, observe_python_env
source = read_source()
draft = plan(
    experiment=study, source=source,
    env=LocalEnvSpec(
        lockfile=GitFileRef(repository=source.repository, commit=source.commit,
                            path="pyproject.toml"),
        python_env=observe_python_env(),
    ),
)
frozen = freeze_run_plan(Path.cwd(), draft)
print(json.dumps({"path": frozen.reference.stored_at.path, "run_id": draft.run_id}))
""",
        ),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    prepared = json.loads(preparation.stdout)
    subprocess.run(("git", "-C", str(root), "add", "experiments"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=VIPER tests",
            "-c",
            "user.email=viper@example.com",
            "commit",
            "--quiet",
            "-m",
            "Save plan",
        ),
        check=True,
    )

    async def execute() -> None:
        """Run the saved plan from a client whose directory differs from the root."""
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "viper.mcp", "--root", str(root), "--access", "execute"],
            cwd=tmp_path,
        )
        async with Client(server, read_timeout_seconds=120) as client:
            result = await client.call_tool("run", {"run_spec": prepared["path"]})
            assert not result.is_error, result.structured_content
            assert result.structured_content["run_id"] == prepared["run_id"]
            resolved = Path(result.structured_content["resolved_run"])
            model = resolved.parent / "artifacts/train/model/model.json"
            assert json.loads(model.read_text())["weight"] == pytest.approx(2, abs=1e-5)
            if journal:
                model_before_publication = model.read_bytes()
                passages = parse_journal(journal_raw)
                expected = encode_journal(tuple(passage.text for passage in passages))
                assertions = await client.call_tool(
                    "search_assertions", {"query": {"kinds": ["observation"]}}
                )
                assert not assertions.is_error, assertions.structured_content
                assert assertions.structured_content is not None
                items = assertions.structured_content["page"]["items"]
                assert len(items) == 1
                assertion = JournalAssertion.model_validate(items[0]["record"]["value"])
                assert assertion.text.encode("utf-8") == passages[0].text.encode(
                    "utf-8"
                )
                assert assertion.status == "proposed"
                assert assertion.source is not None
                document = assertion.source.document
                assert isinstance(document.stored_at, LocalFileRef)
                retained = local_artifact_store(document.stored_at).fetch(
                    document.stored_at
                )
                assert retained == journal_raw
                assert document.sha256 == hashlib.sha256(journal_raw).hexdigest()
                assert any(
                    evidence.kind == "measurement" for evidence in assertion.evidence
                )
                found = await client.call_tool(
                    "search_similar",
                    {
                        "query": {
                            "view_id": "journal-qwen3-0.6b",
                            "view_version": expected.encodings[0].encoder_sha256,
                            "values": expected.values[0],
                        }
                    },
                )
                assert not found.is_error, found.structured_content
                assert found.structured_content is not None
                matches = found.structured_content["page"]["items"]
                assert len(matches) == 1
                reference = matches[0]["vector"]
                location = LocalFileRef.model_validate(reference["stored_at"])
                vector_raw = local_artifact_store(location).fetch(location)
                vector = KnowledgeRecordEnvelope.model_validate(
                    parse_yaml_bytes(vector_raw)
                ).value
                assert isinstance(vector, KnowledgeVector)
                assert isinstance(vector.view, JournalVectorView)
                assert vector.values == expected.values[0]
                assert vector.encoding == expected.encodings[0]
                assert vector.view.embedder == expected.encoder
                assert (
                    expected.encoder.revision
                    == "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
                )
                before_rows = catalog(root=root).runs()
                refreshed = await client.call_tool("knowledge_refresh", {})
                assert not refreshed.is_error
                assert catalog(root=root).runs() == before_rows
                forged = vector.model_dump(mode="json")
                forged["encoding"]["text_sha256"] = "0" * 64
                rejected = await client.call_tool(
                    "publish_vector",
                    {"record": {"record_kind": "vector", "value": forged}},
                )
                assert rejected.is_error
                publication_arguments = {
                    "resolved_run": str(resolved),
                    "trusted_source_repositories": [
                        "https://github.com/example/workspace"
                    ],
                }
                repeated = await client.call_tool(
                    "publish_run_journal", publication_arguments
                )
                assert not repeated.is_error, repeated.structured_content
                assert repeated.structured_content is not None
                publication = repeated.structured_content["result"]
                assert publication["source"] == document.model_dump(mode="json")
                assert publication["assertions"] == [
                    vector.source.model_dump(mode="json")
                ]
                assert publication["vectors"] == [reference]

                # Reject unmatched selectors before any partial assertion publication.
                journal_path = root / "experiments/cpu_quickstart/JOURNAL.md"
                journal_path.write_bytes(
                    b"## Notes\nValid prose.\n\n## Observations\nMetric: absent\n"
                )
                invalid = await client.call_tool(
                    "publish_run_journal", publication_arguments
                )
                assert invalid.is_error
                still_original = await client.call_tool("search_assertions", {})
                assert still_original.structured_content is not None
                assert len(still_original.structured_content["page"]["items"]) == 1

                edited_raw = journal_raw.replace(b"finite loss", b"finite final loss")
                journal_path.write_bytes(edited_raw)
                (root / "viper.toml").write_text(
                    "[workspace]\nschema_version = 2\n[journals]\nenabled = false\n"
                )
                disabled = await client.call_tool(
                    "publish_run_journal", publication_arguments
                )
                assert not disabled.is_error, disabled.structured_content
                assert disabled.structured_content is not None
                assert disabled.structured_content["result"]["skipped"]
                assert disabled.structured_content["result"]["vectors"] == []

                (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
                revised = await client.call_tool(
                    "publish_run_journal", publication_arguments
                )
                assert not revised.is_error, revised.structured_content
                assert revised.structured_content is not None
                revision = revised.structured_content["result"]
                assert (
                    revision["source"]["sha256"]
                    == hashlib.sha256(edited_raw).hexdigest()
                )
                assert revision["source"] != publication["source"]
                assert revision["vectors"] != publication["vectors"]
                all_notes = await client.call_tool("search_assertions", {})
                assert all_notes.structured_content is not None
                assert {
                    item["record"]["value"]["text"]
                    for item in all_notes.structured_content["page"]["items"]
                } == {passages[0].text, parse_journal(edited_raw)[0].text}
                assert model.read_bytes() == model_before_publication
                assert catalog(root=root).runs() == before_rows
            if refresh_knowledge:
                index = catalog(root=root)
                before_runs = index.runs()
                assert before_runs.items
                with closing(sqlite3.connect(index.path)) as connection:
                    execution_tables = tuple(
                        name
                        for (name,) in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                        if name not in {"knowledge_records", "knowledge_primitives"}
                    )
                    before_rows = {
                        table: connection.execute(f"SELECT * FROM {table}").fetchall()
                        for table in execution_tables
                    }
                    candidates = tuple(
                        StageReuseCandidate.model_validate_json(payload)
                        for (payload,) in connection.execute(
                            "SELECT payload_json FROM stage_reuse_keys"
                        )
                    )
                assert candidates
                empty = await client.call_tool("knowledge_refresh", {})
                assert not empty.is_error, empty.structured_content
                assert index.runs() == before_runs
                for candidate in candidates:
                    assert index.reuse_candidate(candidate.key) == candidate
                ontology = OntologySpec(
                    ontology_id="regression",
                    version="1",
                    primitives=(
                        PrimitiveSpec(
                            primitive_id="hopfield",
                            dimension="model-family",
                            label="Hopfield",
                            definition="Associative retrieval model.",
                        ),
                    ),
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
                published = await client.call_tool(
                    "publish_ontology",
                    {
                        "record": KnowledgeRecordEnvelope(
                            record_kind="ontology", value=ontology
                        ).model_dump(mode="json")
                    },
                )
                assert not published.is_error, published.structured_content
                manifest = published.structured_content["publication"]["manifest"]
                for arguments in ({}, {"heads": [manifest]}):
                    refreshed = await client.call_tool("knowledge_refresh", arguments)
                    assert not refreshed.is_error, refreshed.structured_content
                    assert index.runs() == before_runs
                    for candidate in candidates:
                        assert index.reuse_candidate(candidate.key) == candidate
                    with closing(sqlite3.connect(index.path)) as connection:
                        assert {
                            table: connection.execute(
                                f"SELECT * FROM {table}"
                            ).fetchall()
                            for table in execution_tables
                        } == before_rows
                    found = await client.call_tool(
                        "search_primitives", {"query": {"primitive_ids": ["hopfield"]}}
                    )
                    assert not found.is_error
                    assert len(found.structured_content["page"]["items"]) == 1
                before_failure = index.path.read_bytes()
                invalid_manifest = dict(manifest)
                invalid_manifest["sha256"] = "0" * 64
                failed = await client.call_tool(
                    "knowledge_refresh", {"heads": [invalid_manifest]}
                )
                assert failed.is_error
                assert index.path.read_bytes() == before_failure

    anyio.run(execute)
