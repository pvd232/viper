# Stage invocation

## Status

Project parameter identity, decorated callable identity, typed delivery, and
invocation verification are implemented.

## Required claim

VIPER verifies that the exact stage callable frozen by the plan received the
parameter value, input paths, and artifact paths accepted for that stage.

## Implementation

[`execution/_stage.py`](../../src/viper/execution/_stage.py) validates the exact
parameter class before launch and constructs a stable `StageContextBinding`.
[`_workers/stages.py`](../../src/viper/_workers/stages.py) validates the binding, creates
the live `StageContext`, and calls the exact decorated function once. The
attempt stores the resulting `StageInvocationReceipt`; completed stages
reference that same receipt.

## Contract models

`StageImplementationRef` identifies one top-level callable in the project
source:

```python
class StageImplementationRef(ProtocolModel):
    path: PythonRepoRelPath
    symbol: PythonSymbol
    sha256: SHA256
    bytes: int = Field(gt=0)
```

`StageContext` carries one validated stage invocation. It is a runtime
dataclass because it contains attempt-local paths and live metric handles:

```python
ParamsT = TypeVar("ParamsT", bound=viper.parameters.ParameterSet)


@dataclass(frozen=True)
class StageContext(Generic[ParamsT]):
    run_id: RunId
    attempt_id: int
    stage_id: StageId
    params: ParamsT
    inputs: Mapping[InputName, Path]
    artifacts: Mapping[ArtifactName, Path]
    metrics: Mapping[MetricId, MetricHandle]
    numpy_generators: Mapping[HumanId, np.random.Generator]
```

`StageImplementationRef` identifies the callable invoked for the stage. At
execution time, VIPER constructs one `StageContext` from the frozen stage
specification and the active run attempt, then passes that context as the
callable's sole argument.

The stage specification and active attempt join the two models:

```text
StageImplementationRef
├── path: project/stages/train.py
└── symbol: train
          │
          ▼
load the function train
          │
          │ receives
          ▼
StageContext[TrainParameters]
├── params: TrainParameters(epochs=3)
├── inputs: materialized input paths
├── artifacts: writable output paths
├── metrics: runner-owned metric handles
├── numpy_generators: configured named NumPy generators
├── run_id
├── attempt_id
└── stage_id
```

Conceptually, the runner performs this invocation:

```python
train = load_callable(stage.implementation)

params = TrainParameters.model_validate(stage.params)

context = StageContext[TrainParameters](
    run_id=run.run_id,
    attempt_id=attempt.attempt_id,
    stage_id=stage.stage_id,
    params=params,
    inputs=materialized_inputs,
    artifacts=writable_artifact_paths,
    metrics=bound_metric_handles,
    numpy_generators=named_numpy_generators,
)

train(context)
```

`StageImplementationRef` remains stable across invocations because it
identifies source code. VIPER creates a new `StageContext` for each run attempt
because the invocation identity, validated values, and workspace paths belong
to that attempt.

`numpy_generators` maps every name in the frozen
`NumPyRandomnessSpec.generators` field to the exact generator object initialized
inside the controlled child. The mapping is read-only. The callable advances a
generator's internal state by drawing from that generator.

`StageContextBinding` is the serializable description from which the child
constructs `StageContext`. The binding contains stable identities, digests, and
repository-relative paths. The child resolves those paths beneath the active
attempt workspace and attaches the live metric handles and named NumPy
generators before calling the project function.

Each parameterized stage replaces `BaseSpec.script` with:

```python
implementation: StageImplementationRef
```

The source commit, path, symbol, SHA-256, and byte count identify the callable.

## Project interface

The project decorates an ordinary top-level function:

```python
import viper


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    ...


if __name__ == "__main__":
    viper.run(train)
```

The decorator records the stage kind and parameter-model class for authoring.
Plan freezing resolves the function to `StageImplementationRef` and confirms
that the selected `ParameterModelRef` identifies the same class.

`viper.run(train)` starts the [process-startup contract](PROCESS_STARTUP.md).
The installed `viper run` command reaches the same coordinator when a user or
agent executes a complete plan.

## Execution

The controlled child performs this sequence:

```text
load the frozen stage spec
-> verify callable and parameter-model bytes
-> validate params into the selected project class
-> import the selected top-level callable
-> confirm its decorator metadata
-> construct StageContext with the typed parameter object and named generators
-> invoke the callable once
-> record the completed invocation
```

The callable receives validated parameters directly. The same context supplies
the materialized input paths and writable artifact paths selected for that
attempt.

## Persisted evidence

VIPER persists one `StageInvocationReceipt` for each started invocation and
identifies that file through `ResolvedStageInvocationRef`:

```python
class StageContextBinding(ProtocolModel):
    schema_version: Literal[1] = 1
    run_id: RunId
    attempt_id: int = Field(ge=1)
    stage_id: StageId
    parameter_model: ParameterModelRef
    parameter_digest: SHA256
    inputs: dict[InputName, RepoRelPath]
    retrievals: dict[InputName, HttpRetrievalContextBinding] = Field(
        default_factory=dict
    )
    artifacts: dict[ArtifactName, RepoRelPath]
    metric_ids: tuple[MetricId, ...]
    numpy_generator_names: tuple[HumanId, ...]


class StageInvocationReceipt(ProtocolModel):
    implementation: StageImplementationRef
    context: StageContextBinding
    context_digest: SHA256
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: Literal["succeeded", "failed", "cancelled", "preempted"]


class ResolvedStageInvocationRef(ResolvedFileRef):
    kind: Literal["stage_invocation"] = "stage_invocation"
```

The coordinator constructs `StageContextBinding` before launching the child.
Each input value is the repository-relative materialization path declared by
the stage. Each artifact value is the repository-relative output path declared
by the stage. `metric_ids` identifies the runner-owned handles placed in the
runtime context. `numpy_generator_names` is the sorted tuple of configured
generator names. Absolute workspace paths and generator objects exist only in
`StageContext`.

For a download stage, each `retrievals` value binds the terminal response to
the path, SHA-256, and byte count delivered through `DownloadContext`. The
child verifies those body bytes before invoking the download callable. Other
stage kinds use an empty mapping.

The canonical digests are:

```python
context_digest = document_digest(binding)
parameter_digest = document_digest(stage.params)
```

`document_digest()` hashes the model's JSON value with mapping keys sorted and
compact separators. Its result is independent of source-field order. The child
receives the same binding, resolves each logical path beneath its attempt
workspace, attaches the initialized generator objects and metric handles,
constructs `StageContext`, and records the binding and digest in the receipt.
Absolute paths and live handles remain outside the serialized digest.

Every invocation receipt is published at:

```text
experiments/<experiment_id>/runs/<variant_id>/<run_id>/
└── attempts/<attempt_id>/invocations/<stage_id>.yaml
```

`RunAttempt.invocations` references every started stage invocation. A completed
resolved stage references the same receipt. This gives failed invocations a
durable location when execution ends before a resolved stage exists.

The coordinator publishes the receipt as an immutable file before constructing
a successful resolved stage. The resulting `ResolvedStageInvocationRef` can
therefore be retrieved while that stage snapshot is verified. The terminal
attempt later preserves the same reference.

## Verification

| Check | Rule |
|---|---|
| `stage.implementation` | The receipt identifies the callable frozen by the stage spec and run source. |
| `stage.decorator` | The callable's decorator kind and parameter-model class agree with the frozen stage. |
| `parameter_model.identity` | `receipt.context.parameter_model` equals the frozen parameter model. |
| `parameter.value` | `receipt.context.parameter_digest` equals the canonical digest of `stage.params`. |
| `stage.context` | `receipt.context` equals the binding reconstructed from the run, attempt, stage, resolved inputs, declared artifacts, selected metrics, and configured NumPy generator names; its serialized bytes match `context_digest`. |
| `stage.outcome` | A successful resolved stage references one successful invocation receipt. Every started invocation appears in `RunAttempt.invocations` with the terminal outcome observed for that child. |

These checks establish typed delivery to the callable. Project tests establish
how the callable uses each field while producing its scientific result.

## Propagation

| Surface | Required change |
|---|---|
| Protocol | Add `StageImplementationRef`, `StageContextBinding`, `StageInvocationReceipt`, and `ResolvedStageInvocationRef`; replace `BaseSpec.script` on parameterized stages. |
| Decorators | Add one decorator for each stage kind and expose its frozen metadata. |
| Authoring | Resolve the top-level callable and freeze its exact identity. |
| Runtime | Add typed contexts and invoke the callable with the validated project parameter object and configured named NumPy generators. |
| Persistence | Publish each invocation receipt once, reference it from the attempt, and reference successful invocations from their resolved stages. |
| Verification | Apply the six stage-invocation checks. |
| Tests | Replace constant fixture scripts with callables that assert typed parameters and declared paths. |
| Documentation | Show direct Python execution and the whole-plan CLI adapter. |

## Acceptance case

`TinyTrainParameters.epochs` equals `3`. VIPER calls `train(context)` with
`context.params.epochs == 3`. The fixture writes the value `3` into a declared
artifact, and terminal verification accepts the invocation receipt.

The rejection case changes the delivered canonical mapping to `epochs = 2`
while preserving the frozen stage spec. `parameter.value` fails.

## Implementation order

1. Add the implementation-reference, context, and invocation-receipt models.
2. Add the stage decorators and authoring-time callable resolution.
3. Add callable loading and typed context construction.
4. Route every parameterized stage through the callable interface.
5. Add verifier rules and acceptance coverage.
6. Remove the script-path entrypoint after examples migrate.
