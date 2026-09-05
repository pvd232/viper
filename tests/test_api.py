"""Tests for VIPER's typed Python API."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from viper.api import (
    CapabilitiesRequest,
    LocalRunPath,
    RestoreRequest,
    SchemaRequest,
    StatusRequest,
    ValidateStageRequest,
    ViperFailure,
    dispatch,
    get_capabilities,
    get_schema,
    restore_artifacts,
    result_json_bytes,
    status,
    validate_stage,
)
from viper.cli import main
from viper.journal import DurableJournal
from viper.references import LocalFileRef, ResolvedRunRef
from viper.restoration import (
    ArtifactRestoreSelector,
    RestoredArtifact,
    RestoredFile,
    RestoreResult,
)
from viper.api import RunManyRequest, run_many

from viper.execution.results import ExperimentExecutionResult, ExperimentRunResult



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


def test_restore_result_matches_python_api_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Route typed and command restore requests through one execution result."""
    (tmp_path / "viper.toml").write_text(
        "[project]\nschema_version = 1\n",
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
        "[project]\nschema_version = 1\n",
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
