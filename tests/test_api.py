"""Tests for VIPER's typed Python API."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_type_hints

import pytest
from mcp import types
from pydantic import TypeAdapter

from viper.api import (
    HANDLER_REGISTRY,
    KNOWLEDGE_PUBLICATION_MODELS,
    KNOWLEDGE_QUERY_REGISTRY,
    REQUEST_REGISTRY,
    CapabilitiesRequest,
    CatalogRefreshRequest,
    KnowledgeRefreshRequest,
    KnowledgeSearchRequest,
    LocalRunPath,
    OperationName,
    PublishKnowledgeRequest,
    RestoreRequest,
    RunManyRequest,
    SchemaRequest,
    SearchRunsRequest,
    StatusRequest,
    SuccessModel,
    ValidateStageRequest,
    ViperFailure,
    catalog_refresh,
    dispatch,
    get_capabilities,
    get_schema,
    knowledge_refresh,
    publish_ontology,
    restore_artifacts,
    result_json_bytes,
    run_many,
    search_primitives,
    search_runs,
    status,
    validate_stage,
)
from viper.catalog import Catalog, CatalogRefreshResult
from viper.cli import main
from viper.execution.results import ExperimentExecutionResult, ExperimentRunResult
from viper.journal import DurableJournal
from viper.knowledge import (
    KnowledgeRecordEnvelope,
    OntologySpec,
    PrimitiveSpec,
)
from viper.mcp import (
    call_tool,
    prompt_registry,
    read_resource,
    resource_registry,
    resource_templates,
    tool_registry,
)
from viper.references import LocalFileRef, ResolvedRunRef
from viper.restoration import (
    ArtifactRestoreSelector,
    RestoredArtifact,
    RestoredFile,
    RestoreResult,
)


def test_mcp_tool_schemas_match_typed_operations() -> None:
    """Build MCP tools directly from the request and handler registries."""
    first = tool_registry("read")
    second = tool_registry("read")

    assert first == second
    assert tuple(tool.name for tool in first) == tuple(
        sorted(tool.name for tool in first)
    )
    for tool in tool_registry("execute"):
        operation = cast(OperationName, tool.name)
        request = REQUEST_REGISTRY[operation]
        success = get_type_hints(HANDLER_REGISTRY[operation])["return"]
        assert isinstance(success, type) and issubclass(success, SuccessModel)
        schema = request.model_json_schema()
        roots = {"root", "repository_root", "left_root", "right_root"}
        for field in roots:
            schema.get("properties", {}).pop(field, None)
        if "required" in schema:
            schema["required"] = [
                name for name in schema["required"] if name not in roots
            ]
        if operation in KNOWLEDGE_QUERY_REGISTRY:
            query = KNOWLEDGE_QUERY_REGISTRY[operation].model_json_schema()
            schema.setdefault("$defs", {}).update(query.pop("$defs", {}))
            schema["properties"]["query"] = query
            if query.get("required"):
                schema.setdefault("required", []).append("query")
        if operation in KNOWLEDGE_PUBLICATION_MODELS:
            record = schema["$defs"]["KnowledgeRecordEnvelope"]["properties"]
            record["record_kind"] = {
                "type": "string",
                "const": operation.removeprefix("publish_"),
            }
            record["value"] = {
                "anyOf": [
                    {"$ref": f"#/$defs/{model.__name__}"}
                    for model in KNOWLEDGE_PUBLICATION_MODELS[operation]
                ]
            }
            if operation == "publish_impact_policy":
                schema.setdefault("required", []).append("published_at")
                schema["properties"]["published_at"] = {
                    "type": "string",
                    "format": "date-time",
                }
        assert tool.input_schema == schema
        output = TypeAdapter(success | ViperFailure).json_schema()
        output["type"] = "object"
        assert tool.output_schema == output

    result = call_tool(Path.cwd(), "read", "get_capabilities")
    assert result.is_error is False
    assert result.structured_content["operation"] == "get_capabilities"


@pytest.mark.parametrize("kind", ("run", "benchmark", "evidence"))
def test_mcp_resources_are_stateless_inside_startup_root(
    tmp_path: Path, kind: str
) -> None:
    """Resolve catalog resources and prompts from only the fixed startup root."""
    database = tmp_path / ".viper/catalog.sqlite3"
    database.parent.mkdir()
    key = "a" * 64
    reference = json.dumps({"path": "runs/final.yaml", "sha256": "b" * 64})
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.executescript(
                """
                CREATE TABLE sources (
                    source_key TEXT PRIMARY KEY,
                    reference_json TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    error TEXT
                );
                CREATE TABLE runs (source_key TEXT PRIMARY KEY);
                CREATE TABLE benchmarks (source_key TEXT PRIMARY KEY);
                """
            )
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, 1, NULL)",
                (key, reference),
            )
            if kind == "run":
                connection.execute("INSERT INTO runs VALUES (?)", (key,))
            elif kind == "benchmark":
                connection.execute("INSERT INTO benchmarks VALUES (?)", (key,))

    first = resource_registry(tmp_path)
    second = resource_registry(tmp_path)
    assert first == second
    assert tuple(resource.uri for resource in first) == tuple(
        sorted(
            (
                "viper://catalog/head",
                "viper://guide",
                f"viper://{kind}/{key}",
            )
        )
    )
    loaded = read_resource(tmp_path, f"viper://{kind}/{key}")
    assert isinstance(loaded.contents[0], types.TextResourceContents)
    assert json.loads(loaded.contents[0].text) == json.loads(reference)
    assert resource_templates() == resource_templates()
    assert prompt_registry() == prompt_registry()

    rejected = call_tool(tmp_path, "read", "status", {"path": "../outside"})
    assert rejected.is_error
    assert rejected.structured_content["code"] == "invalid_request"
    assert "escapes the MCP startup root" in rejected.structured_content["message"]


@pytest.mark.parametrize("operation", tuple(KNOWLEDGE_QUERY_REGISTRY))
def test_knowledge_query_schemas_are_discoverable_and_enforced(
    tmp_path: Path, operation: OperationName
) -> None:
    """Expose each query's fields and reject invalid fields as request errors."""
    model = KNOWLEDGE_QUERY_REGISTRY[operation]
    schema = get_schema(SchemaRequest(name=model.__name__))
    assert schema.json_schema == model.model_json_schema()
    tool = next(item for item in tool_registry() if item.name == operation)
    assert tool.input_schema["properties"]["query"]["properties"]
    failed = call_tool(tmp_path, "read", operation, {"query": {"unexpected": 1}})
    assert failed.is_error
    assert failed.structured_content["code"] == "invalid_request"


def test_knowledge_operations_match_python_cli_and_mcp(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route one exact knowledge query through every public surface."""
    monkeypatch.setattr("viper.api.resolve_root", lambda root: root.resolve())
    (tmp_path / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    ontology = OntologySpec(
        ontology_id="viper-core",
        version="1",
        primitives=(
            PrimitiveSpec(
                primitive_id="gated-recurrence",
                dimension="model-family",
                label="Gated recurrence",
                definition="A recurrent state transition with learned gates.",
            ),
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    wrong_kind = call_tool(
        tmp_path,
        "execute",
        "publish_assertion",
        {
            "record": KnowledgeRecordEnvelope(
                record_kind="ontology",
                value=ontology,
            ).model_dump(mode="json")
        },
    )
    assert wrong_kind.is_error
    assert wrong_kind.structured_content["code"] == "invalid_request"
    published = publish_ontology(
        PublishKnowledgeRequest(
            root=tmp_path,
            record=KnowledgeRecordEnvelope(
                record_kind="ontology",
                value=ontology,
            ),
        )
    )
    knowledge_refresh(KnowledgeRefreshRequest(root=tmp_path))
    query = {"primitive_ids": ["gated-recurrence"]}
    python_result = search_primitives(
        KnowledgeSearchRequest(root=tmp_path, query=query)
    )

    assert (
        main(
            [
                "--json",
                "knowledge",
                "search",
                "search_primitives",
                "--root",
                str(tmp_path),
                "--query",
                json.dumps(query),
            ]
        )
        == 0
    )
    cli_result = json.loads(capsys.readouterr().out)
    mcp_result = call_tool(
        tmp_path,
        "read",
        "search_primitives",
        {"query": query},
    )

    assert published.publication.record.sha256
    assert cli_result["page"] == python_result.page.model_dump(mode="json")
    assert mcp_result.structured_content["page"] == cli_result["page"]
    read_tools = {tool.name for tool in tool_registry("read")}
    execute_tools = {tool.name for tool in tool_registry("execute")}
    assert "search_primitives" in read_tools
    assert "analyze_impact" not in read_tools | execute_tools
    assert "explain_impact" not in read_tools | execute_tools
    assert "publish_ontology" not in read_tools
    assert "publish_ontology" in execute_tools


def test_api_schema_and_capability_discovery() -> None:
    """Return registered schemas and the installed operation inventory."""
    schema = get_schema(SchemaRequest(name="RunSpec"))
    capabilities = get_capabilities(CapabilitiesRequest())

    assert schema.name == "RunSpec"
    assert schema.json_schema["title"] == "RunSpec"
    assert "validate_run_spec" in capabilities.operations
    assert "preflight" in capabilities.operations
    assert "run" in capabilities.operations
    assert "execute_benchmark" in capabilities.operations
    assert "init_workspace" in capabilities.operations
    assert "plan_diff" in capabilities.operations
    assert "lineage" in capabilities.operations
    assert "status" in capabilities.operations
    assert "compare_runs" in capabilities.operations
    assert "explain_impact" not in capabilities.operations
    assert "analyze_impact" not in capabilities.operations
    assert "catalog_refresh" in capabilities.operations
    assert "search_runs" in capabilities.operations
    assert "RunSpec" in capabilities.schemas
    assert "CompareRunsRequest" in capabilities.schemas
    assert "ExecuteBenchmarkRequest" in capabilities.schemas
    assert "InitWorkspaceRequest" in capabilities.schemas
    assert "ExplainImpactRequest" not in capabilities.schemas
    assert "AnalyzeImpactRequest" not in capabilities.schemas
    assert "CatalogRefreshRequest" in capabilities.schemas
    assert "SearchRunsRequest" in capabilities.schemas
    assert capabilities.execution_backends == ("trusted_local",)


def test_validate_stage_returns_typed_success() -> None:
    """Validate a local stage through the public Python operation."""
    path = Path(__file__).parent / "data/download_stage.yaml"

    result = validate_stage(ValidateStageRequest(path=path))

    assert result.status == "ok"
    assert result.operation == "validate_stage"
    assert result.stage_kind == "download"


def test_dispatch_returns_typed_request_failure() -> None:
    """Return stable request errors before an operation is invoked."""
    result = dispatch("validate_stage", {})

    assert isinstance(result, ViperFailure)
    assert result.origin == "request"
    assert result.code == "invalid_request"


def test_result_json_is_deterministic_and_newline_terminated() -> None:
    """Encode the same result into identical compact JSON bytes."""
    result = get_capabilities(CapabilitiesRequest())

    first = result_json_bytes(result)
    second = result_json_bytes(result)

    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(first)["operation"] == "get_capabilities"
    assert json.loads(first)["warnings"] == []


def test_failure_details_redact_credentials() -> None:
    """Remove secret-bearing fields before a failure reaches public JSON."""
    failure = ViperFailure(
        operation="run",
        origin="application",
        code="retrieval_failed",
        message="retrieval failed",
        details={
            "request": {
                "url": "https://example.test/data",
                "authorization": "Bearer private",
            },
            "secret_name": "DATA_TOKEN",
        },
    )

    value = json.loads(result_json_bytes(failure))

    assert value["details"]["request"]["url"] == "https://example.test/data"
    assert value["details"]["request"]["authorization"] == "<redacted>"
    assert value["details"]["secret_name"] == "<redacted>"


def test_status_returns_latest_durable_attempt_state(tmp_path: Path) -> None:
    """Expose a local attempt journal through the typed API."""
    journal_path = tmp_path / "journal.jsonl"
    journal = DurableJournal(journal_path)
    journal.append(
        "allocated",
        "attempt allocated",
        recorded_at=datetime(2026, 8, 22, tzinfo=UTC),
    )

    result = status(StatusRequest(path=journal_path))

    assert result.state == "allocated"
    assert result.next_states == ("preflighting", "terminal")


def test_restore_result_matches_python_api_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Route typed and command restore requests through one execution result."""
    (tmp_path / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )
    selector = ArtifactRestoreSelector(stage_id="train", artifact_name="model")
    expected = RestoreResult(
        run=ResolvedRunRef(
            sha256="a" * 64,
            bytes=12,
            stored_at=LocalFileRef(
                commit="b" * 64,
                path="runs/example/resolved.yaml",
            ),
        ),
        artifacts=(
            RestoredArtifact(
                selector=selector,
                files=(
                    RestoredFile(
                        path=tmp_path / "model.bin",
                        status="restored",
                    ),
                ),
            ),
        ),
    )
    calls = []

    def fake_restore(
        repository_root: Path,
        run_reference: Path,
        *,
        artifacts: tuple[ArtifactRestoreSelector, ...],
        output: Path | None,
    ) -> RestoreResult:
        """Record the normalized public arguments and return one result."""
        calls.append((repository_root, run_reference, artifacts, output))
        return expected

    monkeypatch.setattr("viper.api.restore_run_artifacts", fake_restore)
    monkeypatch.setattr("viper.api.resolve_root", lambda root: root.resolve())
    request = RestoreRequest(
        run_reference=LocalRunPath(path=Path("runs/example/resolved.yaml")),
        repository_root=tmp_path,
        artifacts=(selector,),
        output=Path("model.bin"),
    )

    direct = restore_artifacts(request)
    status = main(
        [
            "--json",
            "restore",
            "runs/example/resolved.yaml",
            "--root",
            str(tmp_path),
            "--artifacts",
            "train.model",
            "--output",
            "model.bin",
        ]
    )
    output = capsys.readouterr().out

    assert status == 0
    assert json.loads(output) == json.loads(result_json_bytes(direct))
    assert calls == [
        (
            tmp_path,
            Path("runs/example/resolved.yaml"),
            (selector,),
            Path("model.bin"),
        ),
        (
            tmp_path,
            Path("runs/example/resolved.yaml"),
            (selector,),
            Path("model.bin"),
        ),
    ]


def test_run_many_result_matches_python_api_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Route typed and command batch requests through one execution result."""
    (tmp_path / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )
    run_spec = Path("experiments/example/runs/baseline/run/spec.yaml")
    expected = ExperimentExecutionResult(
        runs=(
            ExperimentRunResult(
                variant_id="baseline",
                replicate_id="replicate_01",
                run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                run_spec_path=run_spec,
                status="skipped",
                skip_reason="not started",
            ),
        )
    )
    calls = []

    def fake_run_many(
        repository_root: Path,
        run_specs: tuple[Path, ...],
        *,
        max_concurrency: int,
        timeout_seconds: float | None,
        stop_on_failure: bool,
    ) -> ExperimentExecutionResult:
        """Record normalized batch arguments and return one result."""
        calls.append(
            (
                repository_root,
                run_specs,
                max_concurrency,
                timeout_seconds,
                stop_on_failure,
            )
        )
        return expected

    monkeypatch.setattr("viper.api.execute_many", fake_run_many)
    monkeypatch.setattr("viper.api.resolve_root", lambda root: root.resolve())
    request = RunManyRequest(
        run_specs=(run_spec,),
        root=tmp_path,
        max_concurrency=2,
        timeout_seconds=5.0,
        stop_on_failure=True,
    )

    direct = run_many(request)
    status = main(
        [
            "--json",
            "run-many",
            str(run_spec),
            "--root",
            str(tmp_path),
            "--max-concurrency",
            "2",
            "--timeout-seconds",
            "5",
            "--stop-on-failure",
        ]
    )
    output = capsys.readouterr().out

    assert status == 0
    assert direct.result == expected
    assert json.loads(output) == json.loads(result_json_bytes(direct))
    assert calls == [
        (tmp_path, (run_spec,), 2, 5.0, True),
        (tmp_path, (run_spec,), 2, 5.0, True),
    ]


def test_catalog_result_matches_python_api_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Route catalog refresh and search through the same typed operations."""
    (tmp_path / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )
    run_path = Path("runs/example/resolved.yaml")
    expected = CatalogRefreshResult(
        database=tmp_path / ".viper/catalog.sqlite3",
        sha256="a" * 64,
        accepted=1,
        rejected=0,
    )
    calls: list[tuple[Path, ...]] = []

    class FakeCatalog:
        """Record refresh inputs and return the fixed catalog result."""

        def refresh(self, *, runs: tuple[object, ...]) -> CatalogRefreshResult:
            """Return the fixed result after recording one source tuple."""
            calls.append(tuple(Path(str(item)) for item in runs))
            return expected

    monkeypatch.setattr("viper.api.resolve_root", lambda root: root.resolve())
    monkeypatch.setattr("viper.api._local_fetcher", lambda root, fetcher: object())
    monkeypatch.setattr(
        "viper.api._catalog_run_source",
        lambda root, path, repositories, fetcher: path,
    )
    monkeypatch.setattr("viper.api.catalog", lambda root: FakeCatalog())
    request = CatalogRefreshRequest(
        root=tmp_path,
        run_paths=(run_path,),
        trusted_source_repositories=frozenset({"https://example.test/source"}),
    )

    direct = catalog_refresh(request)
    status_code = main(
        [
            "--json",
            "catalog-refresh",
            str(run_path),
            "--root",
            str(tmp_path),
            "--trust-source",
            "https://example.test/source",
        ]
    )
    output = capsys.readouterr().out

    assert status_code == 0
    assert json.loads(output) == json.loads(result_json_bytes(direct))
    assert calls == [(run_path,), (run_path,)]

    monkeypatch.setattr("viper.api.catalog", lambda root: Catalog(root))
    actual_catalog = Catalog(tmp_path)
    actual_catalog.refresh()
    search = search_runs(SearchRunsRequest(root=tmp_path))
    status_code = main(
        ["--json", "search-runs", "--root", str(tmp_path), "--query", "{}"]
    )
    output = capsys.readouterr().out
    assert status_code == 0
    assert json.loads(output) == json.loads(result_json_bytes(search))
