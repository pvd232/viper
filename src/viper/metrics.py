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
from typing import Any, Literal, TypeVar, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from . import parameters
from ._schema import (
    SHA256,
    DataRole,
    ProtocolModel,
    PythonRepoRelPath,
    PythonSymbol,
)
from .ids import HumanId, MetricId, RunId, StageId
from .references import ResolvedFileRef
from .runtime import (
    ExecutionContext,
    ProcessStartupReceipt,
    PythonEnvironmentSpec,
)

MetricKind = Literal["training", "evaluation", "diagnostic"]


MetricMode = Literal["recompute", "live"]


class FloatComparator(ProtocolModel):
    """Define equality for one recomputed floating-point metric."""

    mode: Literal["exact", "absolute", "relative"] = "exact"
    tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_tolerance(self) -> FloatComparator:
        """Require a positive tolerance for approximate comparison modes."""
        if self.mode != "exact" and self.tolerance == 0:
            raise ValueError("approximate metric comparison requires tolerance")
        if self.mode == "exact" and self.tolerance != 0:
            raise ValueError("exact metric comparison requires zero tolerance")
        return self


class MetricImplementationRef(ProtocolModel):
    """Identify one project-owned metric callable by exact file bytes."""

    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)


class MetricDependency(ProtocolModel):
    """Select one stage value and the data role accepted by a metric."""

    source: Literal["input", "artifact"]
    name: HumanId
    required_data_role: DataRole


class MetricSpec(ProtocolModel):
    """Bind one metric identity to its role, parameters, and implementation."""

    schema_version: Literal[1] = 1
    metric_id: MetricId
    kind: MetricKind
    implementation: MetricImplementationRef
    params: parameters.Metric
    mode: MetricMode
    dependencies: tuple[MetricDependency, ...] = ()
    comparator: FloatComparator | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> MetricSpec:
        """Require one complete live or recomputed metric configuration."""
        identities = tuple(
            (dependency.source, dependency.name) for dependency in self.dependencies
        )
        if len(set(identities)) != len(identities):
            raise ValueError("metric dependencies must be unique")
        if self.mode == "recompute":
            if not self.dependencies:
                raise ValueError("recomputed metrics require dependencies")
            if self.comparator is None:
                raise ValueError("recomputed metrics require a comparator")
        elif self.dependencies or self.comparator is not None:
            raise ValueError("live metrics do not declare dependencies or a comparator")
        if self.kind == "evaluation" and self.mode != "recompute":
            raise ValueError("evaluation metrics require recomputation")
        return self


class ResolvedMetricDependency(ProtocolModel):
    """Bind one metric dependency to its exact persisted files."""

    dependency: MetricDependency
    files: tuple[ResolvedFileRef, ...] = Field(min_length=1)


class MetricExecutionReceipt(ProtocolModel):
    """Record one controlled metric worker execution and its scalar result."""

    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    metric_id: MetricId
    stage_id: StageId
    purpose: Literal["measurement", "verification"]
    implementation: MetricImplementationRef
    params: parameters.Metric
    dependencies: tuple[ResolvedMetricDependency, ...] = Field(min_length=1)
    startup: ProcessStartupReceipt
    execution_context: ExecutionContext
    python_environment: PythonEnvironmentSpec
    value: float = Field(allow_inf_nan=False)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: Literal["succeeded"] = "succeeded"


class Measurement(ProtocolModel):
    """One observed metric value produced during a run stage."""

    run_id: RunId
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    metric_id: MetricId

    value: float = Field(allow_inf_nan=False)
    measured_at: AwareDatetime

    epoch: int | None = Field(default=None, ge=0)
    step: int | None = Field(default=None, ge=0)


class MetricVerificationReceipt(ProtocolModel):
    """Bind one measurement to independent recomputation evidence."""

    schema_version: Literal[1] = 1
    metric_id: MetricId
    stage_id: StageId
    measurement: Measurement
    production: MetricExecutionReceipt
    recomputation: MetricExecutionReceipt
    comparator: FloatComparator
    passed: bool
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_execution_ownership(self) -> MetricVerificationReceipt:
        """Require both workers to select one measurement and frozen invocation."""
        if self.metric_id != self.measurement.metric_id:
            raise ValueError("verification metric ID differs from its measurement")
        if self.stage_id != self.measurement.stage_id:
            raise ValueError("verification stage ID differs from its measurement")
        expected_identity = (
            self.measurement.run_id,
            self.measurement.attempt_id,
            self.measurement.stage_id,
            self.measurement.metric_id,
        )
        for receipt in (self.production, self.recomputation):
            received_identity = (
                receipt.run_id,
                receipt.attempt_id,
                receipt.stage_id,
                receipt.metric_id,
            )
            if received_identity != expected_identity:
                raise ValueError("metric worker identity differs from its measurement")
        if self.production.purpose != "measurement":
            raise ValueError("production receipt must use measurement purpose")
        if self.recomputation.purpose != "verification":
            raise ValueError("recomputation receipt must use verification purpose")
        if (
            self.production.implementation != self.recomputation.implementation
            or self.production.params != self.recomputation.params
            or self.production.dependencies != self.recomputation.dependencies
        ):
            raise ValueError("metric worker invocation bindings differ")
        if self.production.value != self.measurement.value:
            raise ValueError("production value differs from its measurement")
        if self.completed_at < max(
            self.production.completed_at,
            self.recomputation.completed_at,
        ):
            raise ValueError("verification completion precedes a worker receipt")
        return self


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
