"""Expose VIPER's typed API through a local MCP server."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from argparse import ArgumentParser
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal, get_type_hints

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel

from .api import (
    HANDLER_REGISTRY,
    REQUEST_REGISTRY,
    OperationName,
    SuccessModel,
    ViperFailure,
    dispatch,
    result_json_bytes,
)

AccessMode = Literal["read", "execute"]

READ_OPERATIONS: tuple[OperationName, ...] = (
    "compare_runs",
    "get_capabilities",
    "get_schema",
    "lineage",
    "plan_diff",
    "search_artifacts",
    "search_benchmarks",
    "search_measurements",
    "search_runs",
    "status",
    "verify_benchmark",
    "verify_pointer",
    "verify_run",
)
EXECUTION_OPERATIONS: tuple[OperationName, ...] = (
    "catalog_refresh",
    "execute_benchmark",
    "preflight",
    "restore",
    "retry",
    "run",
    "run_many",
)

_ROOT_FIELDS = frozenset({"root", "repository_root", "left_root", "right_root"})
_PROMPTS = (
    "compare_agent_policies",
    "compare_runs",
    "investigate_failure",
    "review_experiment_proposal",
    "review_literature_claim",
    "review_run",
)
_RESOURCE_TEMPLATES = (
    ("artifact", "viper://artifact/{sha256}"),
    ("benchmark", "viper://benchmark/{sha256}"),
    ("knowledge", "viper://knowledge/{sha256}"),
    ("measurement", "viper://measurement/{sha256}"),
    ("run", "viper://run/{sha256}"),
)


def _operations(access: AccessMode) -> tuple[OperationName, ...]:
    """Return the operations granted by one server access mode."""
    operations = READ_OPERATIONS
    if access == "execute":
        operations += EXECUTION_OPERATIONS
    return tuple(sorted(operations))


def _success_model(operation: OperationName) -> type[SuccessModel]:
    """Read the success model from the same handler used by API dispatch."""
    result = get_type_hints(HANDLER_REGISTRY[operation])["return"]
    if not isinstance(result, type) or not issubclass(result, SuccessModel):
        raise TypeError(f"{operation} handler has no concrete success model")
    return result


def tool_registry(access: AccessMode = "read") -> tuple[types.Tool, ...]:
    """Build deterministic MCP tools from VIPER's API registries."""
    tools = []
    for operation in _operations(access):
        request = REQUEST_REGISTRY[operation]
        success = _success_model(operation)
        read_only = operation in READ_OPERATIONS
        tools.append(
            types.Tool(
                name=operation,
                description=HANDLER_REGISTRY[operation].__doc__,
                input_schema=request.model_json_schema(),
                output_schema=success.model_json_schema(),
                annotations=types.ToolAnnotations(
                    read_only_hint=read_only,
                    destructive_hint=not read_only,
                    idempotent_hint=read_only,
                    open_world_hint=False,
                ),
            )
        )
    return tuple(tools)


def _paths(value: object) -> Iterator[Path]:
    """Yield every local path carried by one validated request."""
    if isinstance(value, Path):
        yield value
    elif isinstance(value, BaseModel):
        yield from _paths(value.model_dump(mode="python"))
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _paths(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _paths(item)


def _request_payload(
    root: Path,
    operation: OperationName,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind an MCP request to the server root before API dispatch."""
    payload = dict(arguments)
    request_type = REQUEST_REGISTRY[operation]
    for field in _ROOT_FIELDS & request_type.model_fields.keys():
        supplied = payload.get(field)
        if supplied is not None and Path(supplied).resolve() != root:
            raise ValueError(f"{field} differs from the MCP startup root")
        payload[field] = root

    request = request_type.model_validate(payload)
    for path in _paths(request):
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"request path escapes the MCP startup root: {path}")
    return payload


def call_tool(
    root: Path,
    access: AccessMode,
    name: str,
    arguments: Mapping[str, Any] | None = None,
) -> types.CallToolResult:
    """Validate and dispatch one MCP tool call through the typed API."""
    allowed = _operations(access)
    if name not in allowed:
        raise ValueError(f"MCP tool is unavailable in {access} mode: {name}")
    operation = name
    payload = _request_payload(root.resolve(), operation, arguments or {})
    result = dispatch(operation, payload)
    document = json.loads(result_json_bytes(result))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(document))],
        structured_content=document,
        is_error=isinstance(result, ViperFailure),
    )


def _catalog_sources(root: Path) -> tuple[tuple[str, str, str], ...]:
    """Load immutable source references from the disposable catalog."""
    database = root / ".viper/catalog.sqlite3"
    if not database.is_file():
        return ()
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT sources.source_key, sources.reference_json,
                   CASE WHEN runs.source_key IS NOT NULL THEN 'run'
                        WHEN benchmarks.source_key IS NOT NULL THEN 'benchmark'
                        ELSE 'evidence' END
            FROM sources
            LEFT JOIN runs USING (source_key)
            LEFT JOIN benchmarks USING (source_key)
            WHERE sources.accepted = 1
            ORDER BY sources.source_key
            """
        ).fetchall()
    return tuple((str(key), str(reference), str(kind)) for key, reference, kind in rows)


def resource_registry(root: Path) -> tuple[types.Resource, ...]:
    """List immutable catalog sources and the current derived catalog head."""
    resources = [
        types.Resource(
            name=f"{kind}:{key}",
            uri=f"viper://{kind}/{key}",
            mime_type="application/json",
        )
        for key, _reference, kind in _catalog_sources(root.resolve())
    ]
    database = root.resolve() / ".viper/catalog.sqlite3"
    if database.is_file():
        resources.append(
            types.Resource(
                name="catalog-head",
                uri="viper://catalog/head",
                mime_type="application/json",
            )
        )
    return tuple(sorted(resources, key=lambda resource: resource.uri))


def resource_templates() -> tuple[types.ResourceTemplate, ...]:
    """Return stable templates for VIPER evidence resources."""
    return tuple(
        types.ResourceTemplate(
            name=name,
            uri_template=template,
            mime_type="application/json",
        )
        for name, template in _RESOURCE_TEMPLATES
    )


def read_resource(root: Path, uri: str) -> types.ReadResourceResult:
    """Read one catalog-backed resource without changing server state."""
    project_root = root.resolve()
    if uri == "viper://catalog/head":
        database = project_root / ".viper/catalog.sqlite3"
        if not database.is_file():
            raise ValueError("catalog head is unavailable")
        payload = {
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "sources": len(_catalog_sources(project_root)),
        }
        ttl = 1_000
    else:
        matches = [
            reference
            for key, reference, kind in _catalog_sources(project_root)
            if uri == f"viper://{kind}/{key}"
        ]
        if len(matches) != 1:
            raise ValueError(f"unknown VIPER resource: {uri}")
        payload = json.loads(matches[0])
        ttl = 86_400_000
    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(
                uri=uri,
                mime_type="application/json",
                text=json.dumps(payload, sort_keys=True),
            )
        ],
        ttl_ms=ttl,
        cache_scope="private",
    )


def prompt_registry() -> tuple[types.Prompt, ...]:
    """List the user-selected review prompts in deterministic order."""
    return tuple(
        types.Prompt(
            name=name,
            description=f"Prepare the {name.replace('_', ' ')} review.",
            arguments=[types.PromptArgument(name="reference", required=True)],
        )
        for name in _PROMPTS
    )


def get_prompt(name: str, arguments: Mapping[str, str] | None) -> types.GetPromptResult:
    """Build one review prompt without executing a VIPER operation."""
    if name not in _PROMPTS:
        raise ValueError(f"unknown VIPER prompt: {name}")
    reference = (arguments or {}).get("reference")
    if not reference:
        raise ValueError("prompt reference is required")
    return types.GetPromptResult(
        description=name.replace("_", " "),
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=f"{name.replace('_', ' ').capitalize()}: {reference}",
                ),
            )
        ],
    )


class MCPAdapter:
    """Bind stateless MCP handlers to one repository and access mode."""

    def __init__(self, root: Path, access: AccessMode):
        """Keep one startup root for every request."""
        self.root = root.resolve()
        self.access: AccessMode = access

    async def list_tools(self, _context: Any, _params: Any) -> types.ListToolsResult:
        """Return deterministic tools for the configured access mode."""
        return types.ListToolsResult(tools=list(tool_registry(self.access)))

    async def call_tool(
        self,
        _context: Any,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        """Dispatch one tool request through VIPER's API."""
        return call_tool(self.root, self.access, params.name, params.arguments)

    async def list_resources(
        self, _context: Any, _params: Any
    ) -> types.ListResourcesResult:
        """Return the current catalog resource listing."""
        return types.ListResourcesResult(
            resources=list(resource_registry(self.root)),
            ttl_ms=1_000,
            cache_scope="private",
        )

    async def list_resource_templates(
        self, _context: Any, _params: Any
    ) -> types.ListResourceTemplatesResult:
        """Return the stable resource templates."""
        return types.ListResourceTemplatesResult(
            resource_templates=list(resource_templates()),
            ttl_ms=86_400_000,
            cache_scope="private",
        )

    async def read_resource(
        self,
        _context: Any,
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        """Return one immutable resource or the derived catalog head."""
        return read_resource(self.root, str(params.uri))

    async def list_prompts(
        self, _context: Any, _params: Any
    ) -> types.ListPromptsResult:
        """Return deterministic review prompts."""
        return types.ListPromptsResult(
            prompts=list(prompt_registry()),
            ttl_ms=86_400_000,
            cache_scope="private",
        )

    async def get_prompt(
        self,
        _context: Any,
        params: types.GetPromptRequestParams,
    ) -> types.GetPromptResult:
        """Return one user-selected review prompt."""
        return get_prompt(params.name, params.arguments)


def build_server(root: Path, access: AccessMode = "read") -> Server[None]:
    """Build the official MCP server around one stateless VIPER adapter."""
    adapter = MCPAdapter(root, access)
    return Server(
        "viper",
        version="0.1.0a2",
        on_list_tools=adapter.list_tools,
        on_call_tool=adapter.call_tool,
        on_list_resources=adapter.list_resources,
        on_list_resource_templates=adapter.list_resource_templates,
        on_read_resource=adapter.read_resource,
        on_list_prompts=adapter.list_prompts,
        on_get_prompt=adapter.get_prompt,
    )


async def _run_stdio(root: Path, access: AccessMode) -> None:
    """Serve one MCP connection over standard input and output."""
    server = build_server(root, access)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def serve_stdio(root: Path, access: AccessMode = "read") -> None:
    """Run the local MCP server until its standard-input stream closes."""
    anyio.run(_run_stdio, root, access)


def main(argv: list[str] | None = None) -> int:
    """Parse the isolated MCP process configuration and serve stdio."""
    parser = ArgumentParser(prog="python -m viper.mcp")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--access", choices=("read", "execute"), default="read")
    arguments = parser.parse_args(argv)
    serve_stdio(arguments.root, arguments.access)
    return 0


__all__ = [
    "AccessMode",
    "build_server",
    "call_tool",
    "get_prompt",
    "main",
    "prompt_registry",
    "read_resource",
    "resource_registry",
    "resource_templates",
    "serve_stdio",
    "tool_registry",
]


if __name__ == "__main__":
    raise SystemExit(main())
