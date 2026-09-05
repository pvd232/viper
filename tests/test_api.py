"""Tests for VIPER's typed Python API."""

import json
from datetime import UTC, datetime
from pathlib import Path

from viper.api import (
    CapabilitiesRequest,
    SchemaRequest,
    StatusRequest,
    ValidateStageRequest,
    ViperFailure,
    dispatch,
    get_capabilities,
    get_schema,
    result_json_bytes,
    status,
    validate_stage,
)
from viper.journal import DurableJournal


def test_api_schema_and_capability_discovery() -> None:
    """Return registered schemas and the installed operation inventory."""
    schema = get_schema(SchemaRequest(name="RunSpec"))
    impact_schema = get_schema(SchemaRequest(name="AnalyzeImpactSuccess"))
    capabilities = get_capabilities(CapabilitiesRequest())

    assert schema.name == "RunSpec"
    assert schema.json_schema["title"] == "RunSpec"
    assert "path_search" in impact_schema.json_schema["properties"]
    assert "validate_run_spec" in capabilities.operations
    assert "preflight" in capabilities.operations
    assert "run" in capabilities.operations
    assert "execute_benchmark" in capabilities.operations
    assert "init_project" in capabilities.operations
    assert "plan_diff" in capabilities.operations
    assert "lineage" in capabilities.operations
    assert "status" in capabilities.operations
    assert "compare_runs" in capabilities.operations
    assert "explain_impact" in capabilities.operations
    assert "analyze_impact" in capabilities.operations
    assert "RunSpec" in capabilities.schemas
    assert "CompareRunsRequest" in capabilities.schemas
    assert "ExecuteBenchmarkRequest" in capabilities.schemas
    assert "InitProjectRequest" in capabilities.schemas
    assert "ExplainImpactRequest" in capabilities.schemas
    assert "AnalyzeImpactRequest" in capabilities.schemas
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


def test_analyze_impact_rejects_duplicate_targets_before_execution() -> None:
    """Reject repeated source targets at the public request boundary."""
    result = dispatch(
        "analyze_impact",
        {"targets": ["src/example.py:target", "src/example.py:target"]},
    )

    assert isinstance(result, ViperFailure)
    assert result.origin == "request"
    assert result.code == "invalid_request"


def test_analyze_impact_rejects_an_unbounded_path_search() -> None:
    """Reject ranked traversal limits outside the public bounded contract."""
    result = dispatch(
        "analyze_impact",
        {"targets": ["src/example.py:target"], "path_depth": 6},
    )

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
