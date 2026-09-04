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
from typing import Any, Generic, Literal, TypeVar, cast

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
MetricParamsT = TypeVar("MetricParamsT", bound=parameters.Metric)


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
    """Bind one metric identity to its implementation and frozen parameters."""

    schema_version: Literal[1] = 1
    metric_id: MetricId
    implementation: MetricImplementationRef
    parameter_model: parameters.ParameterModelRef
    params: parameters.Metric
    mode: MetricMode
    dependencies: tuple[MetricDependency, ...] = ()
    comparator: FloatComparator | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> MetricSpec:
        """Require one complete live or recomputed metric configuration."""
        identities = tuple((item.source, item.name) for item in self.dependencies)
        if len(set(identities)) != len(identities):
            raise ValueError("metric dependencies must be unique")
        if self.mode == "recompute":
            if not self.dependencies:
                raise ValueError("recomputed metrics require dependencies")
            if self.comparator is None:
                raise ValueError("recomputed metrics require a comparator")
        elif self.dependencies or self.comparator is not None:
            raise ValueError("live metrics do not declare dependencies or a comparator")
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
    parameter_model: parameters.ParameterModelRef
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
        """Require both workers to select one frozen metric invocation."""
        expected = (
            self.measurement.run_id,
            self.measurement.attempt_id,
            self.stage_id,
            self.metric_id,
        )
        if self.measurement.stage_id != self.stage_id:
            raise ValueError("verification stage ID differs from its measurement")
        if self.measurement.metric_id != self.metric_id:
            raise ValueError("verification metric ID differs from its measurement")
        for receipt in (self.production, self.recomputation):
            received = (
                receipt.run_id,
                receipt.attempt_id,
                receipt.stage_id,
                receipt.metric_id,
            )
            if received != expected:
                raise ValueError("metric worker identity differs from its measurement")
        if self.production.purpose != "measurement":
            raise ValueError("production receipt must use measurement purpose")
        if self.recomputation.purpose != "verification":
            raise ValueError("recomputation receipt must use verification purpose")
        bindings = (
            "implementation",
            "parameter_model",
            "params",
            "dependencies",
        )
        if any(
            getattr(self.production, field) != getattr(self.recomputation, field)
            for field in bindings
        ):
            raise ValueError("metric worker invocation bindings differ")
        if self.production.value != self.measurement.value:
            raise ValueError("production value differs from its measurement")
        latest = self.production.completed_at
        if self.recomputation.completed_at > latest:
            latest = self.recomputation.completed_at
        if self.completed_at < latest:
            raise ValueError("verification completion precedes a worker receipt")
        return self


class MetricError(RuntimeError):
    """Report an invalid metric definition, invocation, or result."""


class MetricContext(BaseModel, Generic[MetricParamsT]):
    """Supply verified paths and frozen parameters to one metric invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inputs: Mapping[str, Path] = Field(default_factory=dict)
    artifacts: Mapping[str, Path] = Field(default_factory=dict)
    params: MetricParamsT


@dataclass(frozen=True)
class MetricDefinition:
    """Store authoring metadata attached to one metric implementation."""

    metric_id: MetricId
    mode: MetricMode


MetricCallable = Callable[[MetricContext], float]
Decorated = TypeVar("Decorated", bound=Callable[..., Any] | type[Any])


def metric(
    *,
    metric_id: MetricId,
    mode: MetricMode,
) -> Callable[[DecoratedMetricT], DecoratedMetricT]:
    """Attach one metric identity and invocation mode to an implementation."""
    definition = MetricDefinition(metric_id=metric_id, mode=mode)

    def decorate(value: DecoratedMetricT) -> DecoratedMetricT:
        """Store the immutable definition on the selected Python object."""
        setattr(value, "__viper_metric__", definition)
        return value

    return decorate


class StatefulMetric(ABC, Generic[MetricParamsT]):
    """Accumulate metric state under one frozen invocation context."""

    @abstractmethod
    def __init__(self, context: MetricContext[MetricParamsT]) -> None:
        """Bind the frozen invocation context once."""

    @abstractmethod
    def update(self, *args: Any, **kwargs: Any) -> None:
        """Consume one stage observation and update internal state."""

    @abstractmethod
    def compute(self) -> float:
        """Return the metric represented by the accumulated state."""


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


def metric_definition(implementation: DecoratedMetric) -> MetricDefinition:
    """Return the metric definition attached to one implementation."""
    definition = getattr(implementation, "__viper_metric__", None)
    if not isinstance(definition, MetricDefinition):
        raise MetricError("metric implementation lacks a VIPER metric decorator")
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
    if definition.mode != spec.mode:
        raise MetricError("metric decorator mode differs from MetricSpec")


class MetricHandle:
    """Bind one live metric implementation, context, and measurement sink."""

    def __init__(
        self,
        implementation: Callable[..., Any] | type[Any],
        sink: MeasurementSink,
        context: MetricContext[Any],
    ) -> None:
        """Instantiate a stateful metric or retain one stateless function."""
        self._sink = sink
        self._context = context
        self._function: Callable[..., Any] | None = None
        self._stateful: StatefulMetric[Any] | None = None
        if inspect.isclass(implementation):
            if not issubclass(implementation, StatefulMetric):
                raise MetricError("live metric class must subclass StatefulMetric")
            self._stateful = implementation(context)
        else:
            self._function = implementation

    def update(self, *args: Any, **kwargs: Any) -> None:
        """Advance one stateful metric with a stage observation."""
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
        """Compute and persist one live measurement."""
        if self._stateful is not None:
            if args or kwargs:
                raise MetricError("stateful metric record uses accumulated state only")
            value = self._stateful.compute()
        else:
            assert self._function is not None
            value = invoke_metric(self._function, self._context, *args, **kwargs)
        return self._sink.append(value, epoch=epoch, step=step)


def bind_live_metric(
    repository_root: Path,
    spec: MetricSpec,
    sink: MeasurementSink,
    context: MetricContext[Any],
) -> MetricHandle:
    """Validate and bind one frozen live metric to its context and sink."""
    if spec.mode != "live":
        raise MetricError("metric handle requires live mode")
    validate_metric_definition(repository_root, spec)
    implementation = load_metric_object(
        repository_root.resolve() / spec.implementation.path,
        spec.implementation.symbol,
    )
    return MetricHandle(implementation, sink, context)


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


DecoratedMetricT = TypeVar(
    "DecoratedMetricT",
    bound=Callable[..., Any] | type[Any],
)

ObjectiveDirection = Literal["min", "max"]

DecoratedMetric = Callable[..., Any] | type[Any]


class MetricDraft(BaseModel, Generic[MetricParamsT]):
    """Hold one configured metric before protocol freezing."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    implementation: DecoratedMetric
    params: MetricParamsT
    dependencies: tuple[MetricDependency, ...] = ()
    comparator: FloatComparator | None = None


class MetricObjectiveDraft(BaseModel):
    """Select one metric and its desired direction of improvement."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    metric: MetricDraft[Any]
    direction: ObjectiveDirection


class MetricCriterionDraft(BaseModel):
    """Apply one optional threshold to a configured metric."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    metric: MetricDraft[Any]
    comparison: Literal["ge", "le"]
    threshold: float = Field(allow_inf_nan=False)


def measure(
    implementation: DecoratedMetric,
    *,
    params: MetricParamsT | None = None,
    dependencies: tuple[MetricDependency, ...] = (),
    comparator: FloatComparator | None = None,
) -> MetricDraft[MetricParamsT | parameters.Metric]:
    """Configure one decorated metric for later freezing."""
    definition = metric_definition(implementation)
    selected_params = parameters.Metric() if params is None else params
    identities = tuple((item.source, item.name) for item in dependencies)
    if len(set(identities)) != len(identities):
        raise MetricError("metric dependencies must be unique")
    if definition.mode == "recompute":
        if not dependencies:
            raise MetricError("recomputed metrics require dependencies")
        if comparator is None:
            raise MetricError("recomputed metrics require a comparator")
    elif dependencies or comparator is not None:
        raise MetricError("live metrics do not declare dependencies or a comparator")
    return MetricDraft(
        implementation=implementation,
        params=selected_params,
        dependencies=dependencies,
        comparator=comparator,
    )


def min(metric: MetricDraft[Any]) -> MetricObjectiveDraft:
    """Make one configured metric a minimization objective."""
    return MetricObjectiveDraft(metric=metric, direction="min")


def max(metric: MetricDraft[Any]) -> MetricObjectiveDraft:
    """Make one configured metric a maximization objective."""
    return MetricObjectiveDraft(metric=metric, direction="max")


def invoke_metric(
    implementation: Callable[..., Any],
    context: MetricContext[Any],
    *args: Any,
    **kwargs: Any,
) -> float:
    """Invoke one stateless metric with its frozen context first."""
    return float(implementation(context, *args, **kwargs))


class MetricObjectiveSpec(ProtocolModel):
    """Persist one objective metric and its direction of improvement."""

    metric_id: MetricId
    direction: ObjectiveDirection
