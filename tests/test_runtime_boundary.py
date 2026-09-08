"""Acceptance tests for the PAC-10 runtime boundary."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import viper.metrics as metrics
import viper.stages as stages

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
        context.stage_id = "other"


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
        _stateful_metric_type(metrics), _ExplodingSink(), object()
    )
    handle.update(2.5)
    assert handle._stateful is not None
    assert handle._stateful.total == 2.5


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
    handle = metrics.MetricHandle(_stateful_metric_type(metrics), sink, object())
    handle.update(1.25)
    handle.update(2.75)
    handle.record(epoch=2, step=40)
    assert sink.calls == [(4.0, {"epoch": 2, "step": 40})]


def test_measurement_sink_writes_one_json_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct and append one validated Measurement per record call."""
    calls = 0
    original = metrics.Measurement

    def count_measurement(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(metrics, "Measurement", count_measurement)
    path = tmp_path / "measurements.jsonl"
    sink = metrics.MeasurementSink(
        path,
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        attempt_id=1,
        stage_id="train",
        metric_id="loss",
    )
    sink.append(0.5, measured_at=datetime(2026, 1, 1, tzinfo=UTC), epoch=1)
    assert calls == 1
    assert len(path.read_text().splitlines()) == 1
