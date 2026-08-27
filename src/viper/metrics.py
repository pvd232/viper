"""Define project metric authoring, invocation, comparison, and measurement."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import math
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from . import parameters
from .ids import MetricId, RunId, StageId
from .protocol import (
    FloatComparator,
    Measurement,
    MetricKind,
    MetricMode,
    MetricSpec,
)


class MetricError(RuntimeError):
    """Report an invalid metric definition, invocation, or result."""


class MetricContext(BaseModel):
    """Supply verified paths and frozen parameters to one metric invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inputs: Mapping[str, Path] = Field(default_factory=dict)
    artifacts: Mapping[str, Path] = Field(default_factory=dict)
    params: parameters.Metric = Field(default_factory=parameters.Metric)


@dataclass(frozen=True)
class MetricDefinition:
    """Store authoring metadata attached to one project metric callable."""

    metric_id: MetricId
    kind: MetricKind
    mode: MetricMode


MetricCallable = Callable[[MetricContext], float]
Decorated = TypeVar("Decorated", bound=Callable[..., Any] | type[Any])


def metric(
    *,
    metric_id: MetricId,
    kind: MetricKind,
    mode: MetricMode,
) -> Callable[[Decorated], Decorated]:
    """Attach VIPER metric metadata to one function or stateful class."""
    definition = MetricDefinition(
        metric_id=metric_id,
        kind=kind,
        mode=mode,
    )

    def decorate(value: Decorated) -> Decorated:
        """Store the immutable definition on the selected Python object."""
        setattr(value, "__viper_metric__", definition)
        return value

    return decorate


class StatefulMetric(ABC):
    """Accumulate changing metric state across training updates."""

    @abstractmethod
    def update(self, *args: Any, **kwargs: Any) -> None:
        """Consume one training observation and update internal state."""

    @abstractmethod
    def compute(self) -> float:
        """Return the metric value represented by the accumulated state."""


def load_metric_object(path: Path, symbol: str) -> Callable[..., Any] | type[Any]:
    """Load one top-level metric function or class from a local Python file."""
    module_name = f"_viper_metric_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise MetricError("metric module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = getattr(module, symbol, None)
    if value is None or not callable(value):
        raise MetricError("metric symbol is absent or is not callable")
    return cast(Callable[..., Any] | type[Any], value)


def load_metric(path: Path, symbol: str) -> MetricCallable:
    """Load one recomputed metric function from a local Python file."""
    value = load_metric_object(path, symbol)
    if inspect.isclass(value):
        raise MetricError("recomputed metric symbol must be a function")
    return cast(MetricCallable, value)


def metric_definition(function: Callable[..., Any]) -> MetricDefinition:
    """Return the immutable decorator metadata attached to one metric callable."""
    definition = getattr(function, "__viper_metric__", None)
    if not isinstance(definition, MetricDefinition):
        raise MetricError("metric callable lacks a VIPER metric decorator")
    return definition


def validate_metric_definition(repository_root: Path, spec: MetricSpec) -> None:
    """Match one decorated metric callable with its frozen metric specification."""
    path = repository_root.resolve() / spec.implementation.path
    raw = path.read_bytes()
    if len(raw) != spec.implementation.bytes:
        raise MetricError("metric implementation byte count differs")
    if hashlib.sha256(raw).hexdigest() != spec.implementation.sha256:
        raise MetricError("metric implementation SHA-256 differs")
    definition = metric_definition(load_metric_object(path, spec.implementation.symbol))
    if definition.metric_id != spec.metric_id:
        raise MetricError("metric decorator ID differs from MetricSpec")
    if definition.kind != spec.kind:
        raise MetricError("metric decorator kind differs from MetricSpec")
    if definition.mode != spec.mode:
        raise MetricError("metric decorator mode differs from MetricSpec")


class MetricHandle:
    """Bind one live metric implementation to its controlled measurement sink."""

    def __init__(
        self,
        implementation: Callable[..., Any] | type[Any],
        sink: MeasurementSink,
    ) -> None:
        """Instantiate stateful metrics and retain stateless functions."""
        self._sink = sink
        self._function: Callable[..., Any] | None = None
        self._stateful: StatefulMetric | None = None
        if inspect.isclass(implementation):
            if not issubclass(implementation, StatefulMetric):
                raise MetricError("live metric class must subclass StatefulMetric")
            self._stateful = implementation()
        else:
            self._function = implementation

    def update(self, *args: Any, **kwargs: Any) -> None:
        """Advance one stateful metric with a stage-provided observation."""
        if self._stateful is None:
            raise MetricError("stateless metric handles do not support update")
        self._stateful.update(*args, **kwargs)

    def record(
        self,
        *args: Any,
        epoch: int | None = None,
        step: int | None = None,
        **kwargs: Any,
    ) -> Measurement:
        """Compute and persist one live measurement owned by the active stage."""
        if self._stateful is not None:
            if args or kwargs:
                raise MetricError(
                    "stateful metric record uses the accumulated state only"
                )
            value = self._stateful.compute()
        else:
            assert self._function is not None
            value = self._function(*args, **kwargs)
        return self._sink.append(float(value), epoch=epoch, step=step)


def bind_live_metric(
    repository_root: Path,
    spec: MetricSpec,
    sink: MeasurementSink,
) -> MetricHandle:
    """Validate and bind one frozen live metric to a measurement sink."""
    if spec.mode != "live":
        raise MetricError("metric handle requires live mode")
    validate_metric_definition(repository_root, spec)
    implementation = load_metric_object(
        repository_root.resolve() / spec.implementation.path,
        spec.implementation.symbol,
    )
    return MetricHandle(implementation, sink)


def compare_metric_values(
    recorded: float,
    recomputed: float,
    comparator: FloatComparator,
) -> bool:
    """Compare one recorded value with its recomputed value."""
    if comparator.mode == "exact":
        return recorded == recomputed
    if comparator.mode == "absolute":
        return math.isclose(
            recorded, recomputed, rel_tol=0, abs_tol=comparator.tolerance
        )
    return math.isclose(recorded, recomputed, rel_tol=comparator.tolerance, abs_tol=0)


class MeasurementSink:
    """Append synchronized Measurement rows owned by one active stage."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: RunId,
        attempt_id: int,
        stage_id: StageId,
        metric_id: MetricId,
    ) -> None:
        """Bind the sink to one canonical stage and metric identity."""
        self.path = path
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.stage_id = stage_id
        self.metric_id = metric_id

    def append(
        self,
        value: float,
        *,
        measured_at: datetime | None = None,
        epoch: int | None = None,
        step: int | None = None,
    ) -> Measurement:
        """Construct, append, flush, and synchronize one measurement row."""
        measurement = Measurement(
            run_id=self.run_id,
            attempt_id=self.attempt_id,
            stage_id=self.stage_id,
            metric_id=self.metric_id,
            value=value,
            measured_at=datetime.now(UTC) if measured_at is None else measured_at,
            epoch=epoch,
            step=step,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(measurement.model_dump_json().encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return measurement
