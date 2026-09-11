"""Acceptance tests for the PAC-10 runtime boundary."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import torch
from pydantic import ValidationError

import viper.metrics as metrics
import viper.stages as stages
from viper.resume import DataLoaderConfiguration
from viper.runtime import ParallelismSpec, ReproducibilitySpec, resolve_execution_policy

PAIR_BLOCK_ID = "P3-PAC-10"
REQUIREMENT_ID = "PAC-10"


def test_runtime_contexts_are_frozen_slotted_dataclasses() -> None:
    """Keep live contexts lightweight while preventing reassignment."""
    for runtime_type in (stages.Context, metrics.MetricContext):
        assert dataclasses.is_dataclass(runtime_type)
        assert getattr(runtime_type, "__dataclass_params__").frozen is True
        assert "__slots__" in runtime_type.__dict__
        assert "model_fields" not in runtime_type.__dict__


def test_runtime_context_rejects_field_reassignment() -> None:
    """Preserve the logical immutability supplied by frozen dataclasses."""
    context = stages.Context.__new__(stages.Context)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        context.stage_id = "other"  # pyright: ignore[reportAttributeAccessIssue]


def _stateful_metric_type(metrics_module: Any) -> type[Any]:
    """Create one valid stateful metric against the runtime module."""

    class TestMetric(metrics_module.StatefulMetric):
        """Accumulate raw values without constructing protocol records."""

        def __init__(self, context: object) -> None:
            del context
            self.total = 0.0

        def update(self, value: Any) -> None:
            """Accept an arbitrary tensor-like value by reference."""
            self.total += float(value)

        def compute(self) -> float:
            """Return the in-memory aggregate."""
            return self.total

    return TestMetric


class _ExplodingSink:
    """Fail if a high-frequency update touches persistence."""

    def append(self, value: float, **kwargs: object) -> object:
        """Reject every attempted durable append."""
        del value, kwargs
        raise AssertionError("MetricHandle.update touched the persistence sink")


def test_metric_update_does_not_validate_or_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward raw batch values only to the in-memory metric state."""

    def reject_measurement(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("MetricHandle.update constructed Measurement")

    monkeypatch.setattr(metrics, "Measurement", reject_measurement)
    handle = metrics.MetricHandle(
        _stateful_metric_type(metrics),
        cast("Any", _ExplodingSink()),
        cast("Any", object()),
    )
    handle.update(2.5)
    assert handle._stateful is not None
    assert getattr(handle._stateful, "total") == 2.5


class _RecordingSink:
    """Record append calls without performing file I/O."""

    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, object]]] = []

    def append(self, value: float, **kwargs: object) -> object:
        """Retain one measurement publication request."""
        self.calls.append((value, kwargs))
        return object()


def test_metric_record_persists_one_measurement() -> None:
    """Publish exactly one measurement at an explicit reporting boundary."""
    sink = _RecordingSink()
    handle = metrics.MetricHandle(
        _stateful_metric_type(metrics), cast("Any", sink), cast("Any", object())
    )
    handle.update(1.25)
    handle.update(2.75)
    handle.record(epoch=2, step=40)
    assert sink.calls == [(4.0, {"epoch": 2, "step": 40})]


def test_measurement_sink_constructs_one_measurement(tmp_path: Path) -> None:
    """Construct exactly one Measurement per append."""
    sink = metrics.MeasurementSink(
        tmp_path / "measurements.jsonl",
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        attempt_id=1,
        stage_id="train",
        metric_id="loss",
    )

    with patch.object(metrics, "Measurement", wraps=metrics.Measurement) as constructor:
        sink.append(0.5)
        constructor.assert_called_once()


def test_measurement_sink_writes_expected_record(tmp_path: Path) -> None:
    """Persist one record with the supplied identity, value, and timestamp."""
    path = tmp_path / "measurements.jsonl"
    measured_at = datetime(2026, 1, 1, tzinfo=UTC)
    sink = metrics.MeasurementSink(
        path,
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        attempt_id=1,
        stage_id="train",
        metric_id="loss",
    )

    returned = sink.append(0.5, measured_at=measured_at, epoch=1)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    saved = metrics.Measurement.model_validate_json(lines[0])
    assert saved == returned
    assert saved.run_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert saved.attempt_id == 1
    assert saved.stage_id == "train"
    assert saved.metric_id == "loss"
    assert saved.value == 0.5
    assert saved.measured_at == measured_at
    assert saved.epoch == 1
    assert saved.step is None


def test_execution_policy_reproducible_default() -> None:
    """Require deterministic operations and conservative default parallelism."""
    policy, settings = resolve_execution_policy()
    assert policy.mode == "reproducible"
    assert policy.version == 1
    assert settings.determinism.model_dump() == {
        "deterministic_algorithms": True,
        "deterministic_warn_only": False,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "cublas_workspace_config": ":4096:8",
    }
    assert settings.parallelism.torch_intraop_threads == 1
    assert settings.parallelism.torch_interop_threads == 1
    assert settings.parallelism.dataloader.workers == 0


def test_execution_policy_relaxed_allows_nondeterminism() -> None:
    """Permit nondeterministic algorithms without reducing numerical precision."""
    _, strict = resolve_execution_policy()
    policy, relaxed = resolve_execution_policy("relaxed")
    assert policy.mode == "relaxed"
    assert relaxed.determinism.model_dump() == {
        "deterministic_algorithms": False,
        "deterministic_warn_only": False,
        "cudnn_deterministic": False,
        "cudnn_benchmark": True,
        "cublas_workspace_config": None,
    }
    assert relaxed.precision == strict.precision
    assert relaxed.precision.float32_matmul_precision == "highest"
    assert relaxed.precision.cudnn_allow_tf32 is False
    assert relaxed.precision.autocast_enabled is False
    assert relaxed.numpy_randomness == strict.numpy_randomness
    assert relaxed.parallelism.torch_intraop_threads == torch.get_num_threads()
    assert relaxed.parallelism.torch_interop_threads == torch.get_num_interop_threads()


@pytest.mark.parametrize("mode", ["reproducible", "relaxed"])
def test_execution_policy_parallelism_is_independent(mode: str) -> None:
    """Allow worker and thread choices without changing the numerical policy."""
    resources = ParallelismSpec(
        process_count=1,
        torch_intraop_threads=4,
        torch_interop_threads=2,
        dataloader=DataLoaderConfiguration(workers=2, prefetch_factor=2),
    )
    policy, settings = resolve_execution_policy(cast(Any, mode), parallelism=resources)
    assert policy.mode == mode
    assert settings.parallelism == resources
    assert settings.parallelism is not resources
    assert settings.determinism.deterministic_algorithms == (mode == "reproducible")


def test_execution_policy_saved_settings_preserve_parallelism() -> None:
    """Keep resolved thread counts in saved settings without consulting the host."""
    _, settings = resolve_execution_policy("relaxed")
    saved = settings.model_dump_json()
    restored = ReproducibilitySpec.model_validate_json(saved)
    assert restored == settings
    assert restored.determinism.deterministic_algorithms is False


def test_execution_policy_custom_preserves_and_copies_settings() -> None:
    """Keep explicit numerical settings custom and detach caller-owned mappings."""
    _, settings = resolve_execution_policy()
    settings.numpy_randomness.generators["sampling"] = "PCG64"
    policy, copied = resolve_execution_policy(settings)
    assert policy.mode == "custom"
    assert copied == settings
    settings.numpy_randomness.generators.clear()
    assert copied.numpy_randomness.generators == {"sampling": "PCG64"}
    with pytest.raises(ValueError, match="already include parallelism"):
        resolve_execution_policy(settings, parallelism=settings.parallelism)


def test_execution_policy_revalidates_custom_settings() -> None:
    """Reject unchecked custom copies with inconsistent autocast settings."""
    _, settings = resolve_execution_policy()
    invalid = settings.model_copy(
        update={
            "precision": settings.precision.model_copy(
                update={"autocast_enabled": True, "autocast_dtype": None}
            )
        }
    )
    with pytest.raises(ValidationError, match="autocast_dtype is required"):
        resolve_execution_policy(invalid)


@pytest.mark.parametrize("selection", ["optimized", "custom", "unknown"])
def test_execution_policy_rejects_unknown_names(selection: str) -> None:
    """Require a supported preset name or explicit custom settings."""
    with pytest.raises(ValueError, match="execution policy must be"):
        resolve_execution_policy(cast(Any, selection))
