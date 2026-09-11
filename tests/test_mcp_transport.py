"""Exercise discovery and tool calls through the installed MCP stdio client."""

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from mcp import types
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError

from viper import _subprocess as subprocess
from viper.catalog import catalog
from viper.journal import DurableJournal
from viper.mcp import call_tool, get_prompt, prompt_registry, tool_registry


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


def test_stdio_executes_a_saved_training_plan(tmp_path: Path) -> None:
    """Execute real training through MCP and inspect the resulting model bytes."""
    root = tmp_path / "workspace"
    source_root = Path(__file__).parents[1]
    shutil.copytree(
        source_root / "examples",
        root / "examples",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(source_root / "pyproject.toml", root / "pyproject.toml")
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
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

    anyio.run(execute)
