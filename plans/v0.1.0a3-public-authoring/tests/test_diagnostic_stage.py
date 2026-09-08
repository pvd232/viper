"""Planned acceptance tests for the PAC-04 terminal diagnostic stage."""

from __future__ import annotations

import importlib
import inspect

import pytest
from pydantic import TypeAdapter, ValidationError

PAIR_BLOCK_ID = "P2-PAC-04"
REQUIREMENT_ID = "PAC-04"
PLANNED_DESTINATION = "tests/test_diagnostic_stage.py"


def test_diagnostic_has_one_public_identifier() -> None:
    """Use diagnostic consistently for the config, decorator, and kind."""
    config = importlib.import_module("viper.config")
    stages = importlib.import_module("viper.stages")
    assert hasattr(config, "DiagnosticConfig")
    assert hasattr(stages, "diagnostic")
    assert not hasattr(config, "DiagnoseConfig")
    assert not hasattr(stages, "diagnose")


def test_diagnostic_decorator_binds_the_diagnostic_kind() -> None:
    """Attach diagnostic identity to one workspace callable."""
    config = importlib.import_module("viper.config")
    stages = importlib.import_module("viper.stages")

    class DiagnosticConfig(config.DiagnosticConfig):
        top_k: int

    @stages.diagnostic(config=DiagnosticConfig)
    def inspect_model(context: object) -> None:
        del context

    definition = stages.stage_definition(inspect_model)
    assert definition.kind == "diagnostic"
    assert definition.config_type is DiagnosticConfig


def test_diagnostic_spec_is_in_frozen_and_resolved_unions() -> None:
    """Deserialize diagnostic documents through both stage unions."""
    stages = importlib.import_module("viper.stages")
    spec_mapping = TypeAdapter(stages.Spec).json_schema()["discriminator"]["mapping"]
    resolved_mapping = TypeAdapter(stages.ResolvedSpec).json_schema()[
        "discriminator"
    ]["mapping"]
    assert "DiagnosticSpec" in spec_mapping["diagnostic"]
    assert "ResolvedDiagnosticSpec" in resolved_mapping["diagnostic"]


def test_diagnostic_spec_has_no_optimization_objective() -> None:
    """Keep diagnostics descriptive rather than optimizing."""
    stages = importlib.import_module("viper.stages")
    assert "objective" not in stages.DiagnosticSpec.model_fields


def test_diagnostic_is_excluded_from_estimator_and_benchmark_selection() -> None:
    """Prevent a terminal report stage from becoming a selected model result."""
    runs = importlib.import_module("viper.runs")
    benchmark = importlib.import_module("viper.benchmark")
    run_source = inspect.getsource(runs.RunSpec.validate_common_invariants)
    benchmark_schema = benchmark.BenchmarkSpec.model_json_schema()
    assert "parameters" in run_source
    assert "diagnostic" not in str(benchmark_schema)


def test_diagnostic_output_cannot_feed_a_later_stage() -> None:
    """Reject downstream computation from a terminal diagnostic output."""
    stages = importlib.import_module("viper.stages")
    validator = getattr(stages, "validate_stage_order")
    with pytest.raises(
        ValueError,
        match=r"diagnostic.+report.+downstream",
    ):
        validator(
            (
                {"stage_id": "diagnostic", "kind": "diagnostic"},
                {
                    "stage_id": "downstream",
                    "kind": "build",
                    "inputs": {
                        "report": {
                            "kind": "future",
                            "producer_stage_id": "diagnostic",
                            "name": "report",
                        }
                    },
                },
            )
        )


def test_diagnostic_accepts_descriptive_metrics() -> None:
    """Permit measurements that describe a diagnostic result."""
    metrics = importlib.import_module("viper.metrics")
    assert "diagnostic" in metrics.MetricKind.__args__


def test_diagnostic_dispatch_is_not_an_eval_fallback() -> None:
    """Require a dedicated resolved model for diagnostic execution."""
    resolution = importlib.import_module("viper.execution._resolution")
    source = inspect.getsource(resolution.resolve_stage)
    assert "ResolvedDiagnosticSpec" in source
    assert "unsupported stage kind" in source


def test_diagnostic_rejects_an_objective_field() -> None:
    """Reject persisted diagnostic documents that request optimization."""
    stages = importlib.import_module("viper.stages")
    payload = {"kind": "diagnostic", "schema_version": 2, "objective": {}}
    with pytest.raises(ValidationError, match="objective"):
        stages.DiagnosticSpec.model_validate(payload)
