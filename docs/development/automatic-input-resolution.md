# Automatic artifact capture and input resolution

Users write decorated stage functions and typed parameter classes. VIPER
creates the references that connect one stage's output to another stage's
input. This contract defines how VIPER creates those references. A later
contract will define explicit harness mode.

## 1. Status

**Contract status:** audited authoring and freezing contract; implementation
pending.

**Current:** Project code defines stages with `@viper.download_stage`,
`@viper.train_stage`, and a subclass of `viper.parameters.Train`. Each stage
function receives a `StageContext`. The function reads input paths from
`context.inputs` and writes files at the paths in `context.artifacts`.
See [`README.md`](../../README.md#define-a-stage) and
[`src/viper/stages.py`](../../src/viper/stages.py).

**Current:** `DownloadSpec` accepts HTTP requests. `TrainSpec` accepts
`ExternalInputRef`, `StoredInputRef`, or `FutureInputRef`. Users must choose and
construct those internal reference objects themselves.
See [`src/viper/stages.py`](../../src/viper/stages.py).

**Proposed:** Four project-owned stage kinds use `@viper.build`,
`@viper.embed`, `@viper.train`, or `@viper.evaluate`. The decorator's
`params=` argument selects the typed parameter class. `viper.stage()` receives
one validated instance of that class. `viper.download()` creates the
runner-owned HTTP stage directly.

The keys in `plan.stages` become the stage IDs. A user can pass a local file, an
artifact from an earlier stage, or an artifact from an earlier run to
`viper.stage()`. `viper.freeze()` converts that value into `ExternalInputRef`,
`FutureInputRef`, or `StoredInputRef`. For an earlier run, VIPER also writes an
`ArtifactPointer`.

This contract changes the Python API. It also makes VIPER execute
`DownloadSpec`. The four project-owned stage types keep using `StageContext`.
They also keep the same artifact and input paths. The download contract makes
`ResolvedHttpRetrieval.body` equal the matching
`ResolvedSingleFileArtifact.file`.

[`download-retrieval-artifacts.md`](download-retrieval-artifacts.md) owns that
receipt-to-artifact identity rule.
[`external-input-roots.md`](external-input-roots.md) owns the distinct root,
artifact, and consumer-edge roles of the resulting records. This contract owns
the Python expression that selects the artifact and compiles the internal
input reference.

## 2. Required claim

When a user passes a VIPER artifact into a training stage, VIPER records which
stage produced it and which artifact the user chose. VIPER writes the required
input reference. The training function receives the verified path through
`StageContext.inputs`.

The user writes the stage decorator, parameter class, and training function.
`viper.freeze()` writes a same-run reference or pointer. VIPER executes each
`DownloadSpec`. A custom transport handles any project-specific HTTP request.

## 3. Current gap

The fixed scenario is:

```text
download a dataset
-> declare the downloaded dataset as a stage artifact
-> train a model on that dataset
```

The current path is:

```text
DownloadSpec.artifacts["dataset"]
-> completed download stage records the resolved artifact
-> TrainSpec.inputs["dataset"]
-> user selects FutureInputRef or StoredInputRef
-> runtime materializes the input
-> train(context) reads context.inputs["dataset"]
```

**Inspected:** `FutureInputRef` carries `producer_stage_id` and
`producer_artifact` for an earlier stage in the same run.
[`src/viper/inputs.py`](../../src/viper/inputs.py)

**Inspected:** `StoredInputRef` carries an `ArtifactPointerRef`, a
materialization path, and a data role for an artifact from a completed run.
[`src/viper/inputs.py`](../../src/viper/inputs.py)

**Inspected:** `freeze_run_plan()` validates authored stage specifications and
writes frozen stage and run files. It currently preserves the input reference
already present in the stage specification. Pointer-document construction
belongs to the proposed authoring operation.
[`src/viper/authoring.py`](../../src/viper/authoring.py)

**Inspected:** The executor follows `StoredInputRef.pointer` and calls
`verify_promoted_artifact()`. It then places the verified files at the declared
input path and passes that path to `StageContext`.
[`src/viper/execution/_materialization.py`](../../src/viper/execution/_materialization.py)

VIPER can already execute all three reference types. Users still have to create
the reference objects themselves. The proposed Python API accepts ordinary
files and artifact handles. `viper.freeze()` creates the required reference.

## 4. Contract models

### Target stage decorators

The four project-owned stage decorators use `params=` for the parameter class:

```python
from my_cool_model_acronym.training import train_model

class TrainParams(viper.params.Train):
    epochs: int
    learning_rate: float


@viper.train(params=TrainParams)
def train(context: viper.StageContext[TrainParams]) -> None:
    dataset = context.inputs["dataset"]
    parameters = context.artifacts["parameters"]
    train_model(
        dataset,
        parameters,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
```

The decorator records `TrainParams` as the parameter model. `viper.stage()`
later receives `TrainParams(epochs=3, learning_rate=0.1)` and places those
values in `TrainSpec.params`. The executor continues to pass a `Path` through
`context.inputs["dataset"]`.

The target decorator signatures are:

```python
def build(*, params: type[BuildParamsT]) -> StageDecorator[BuildParamsT]: ...
def embed(*, params: type[EmbedParamsT]) -> StageDecorator[EmbedParamsT]: ...
def train(*, params: type[TrainParamsT]) -> StageDecorator[TrainParamsT]: ...
def evaluate(*, params: type[EvaluateParamsT]) -> StageDecorator[EvaluateParamsT]: ...
def http_transport(
    *,
    transport_id: HumanId,
    params: type[TransportParamsT] = parameters.HttpTransport,
) -> HttpTransportDecorator[TransportParamsT]: ...
```

`viper.params` is the public alias for the existing parameter categories in
`viper.parameters`. The persisted field remains `parameter_model` because it
stores a `ParameterModelRef`, while the Python authoring keyword is `params`.

### Target artifact and transport drafts

Users give VIPER three kinds of Python definitions:

```text
artifact loader function
-> ArtifactLoaderRef

HTTP transport function
-> HttpTransportImplementationRef

parameter class
-> ParameterModelRef
```

`viper.freeze()` records the source file, Python symbol, SHA-256 digest, and
byte count for each definition. The frozen YAML stores those records.

```python
class SingleFileArtifactDraft(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    kind: Literal["file"] = "file"
    path: RepoRelPath
    loader: Callable[[Path], object]
    data_role: DataRole


class BundleArtifactDraft(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    kind: Literal["bundle"] = "bundle"
    path: RepoRelPath
    loader: Callable[[Path], object]
    data_role: DataRole


ArtifactDraft = Annotated[
    SingleFileArtifactDraft | BundleArtifactDraft,
    Field(discriminator="kind"),
]


@dataclass(frozen=True)
class CustomHttpTransportDraft:
    implementation: HttpTransportCallable[Any]
    params: parameters.HttpTransport
    executables: tuple[ExternalExecutableSpec, ...] = ()


HttpTransportDraft = BuiltinHttpTransportSpec | CustomHttpTransportDraft
```

A custom transport can use VIPER's base settings. The user writes:

```python
@viper.http_transport(transport_id="project_httpx")
def transfer(context: viper.HttpTransportContext) -> viper.HttpTransportResult:
    ...
```

VIPER uses `viper.params.HttpTransport` for that transport.

A configurable transport defines its own parameter class. The decorator's
`params=` argument receives the class. `viper.transport(params=...)` receives
the values for one run.

### Target stage drafts

`DownloadSpecDraft` contains the requests, transport, policy, and artifact
declarations. VIPER runs each request. The other four stage drafts contain one
decorated project function and one parameter object.

```python
@dataclass(frozen=True)
class StageDraftArtifactRef:
    producer: "StageDraft"
    artifact_name: ArtifactName


class FileInputDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RepoRelPath
    data_role: DataRole


class RunArtifactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_run: Path | ResolvedRunRef
    stage_id: StageId
    artifact_name: ArtifactName


StageInputDraft = FileInputDraft | StageDraftArtifactRef | RunArtifactDraft


class BaseSpecDraft(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    kind: str
    environment: EnvironmentSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()
    artifacts: dict[ArtifactName, ArtifactDraft] = Field(min_length=1)


class ParameterizedSpecDraft(BaseSpecDraft):
    implementation: DecoratedStage
    params: parameters.ParameterSet


class DownloadSpecDraft(BaseSpecDraft):
    kind: Literal["download"] = "download"
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    transport: HttpTransportDraft
    policy: HttpRetrievalPolicy


class InternalSpecDraft(ParameterizedSpecDraft):
    inputs: dict[InputName, StageInputDraft] = Field(min_length=1)


class BuildSpecDraft(InternalSpecDraft):
    kind: Literal["build"] = "build"
    params: parameters.Build


class EmbedSpecDraft(InternalSpecDraft):
    kind: Literal["embed"] = "embed"
    params: parameters.Embed


class TrainSpecDraft(InternalSpecDraft):
    kind: Literal["train"] = "train"
    params: parameters.Train


class EvaluateSpecDraft(InternalSpecDraft):
    kind: Literal["evaluate"] = "evaluate"
    evaluation_id: EvaluationId
    metric_ids: tuple[MetricId, ...] = Field(min_length=1)
    split_inputs: tuple[InputName, ...] = Field(min_length=1)
    params: parameters.Evaluate


StageSpecDraft = Annotated[
    DownloadSpecDraft
    | BuildSpecDraft
    | EmbedSpecDraft
    | TrainSpecDraft
    | EvaluateSpecDraft,
    Field(discriminator="kind"),
]


class StageDraft(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    spec: StageSpecDraft

    @property
    def artifacts(self) -> dict[ArtifactName, StageDraftArtifactRef]:
        return {
            name: StageDraftArtifactRef(
                producer=self,
                artifact_name=name,
            )
            for name in self.spec.artifacts
        }
```

`DownloadSpecDraft` rejects unequal input and artifact keys and rejects every
artifact value except `SingleFileArtifactDraft`. The frozen `DownloadSpec`
repeats both checks, so direct frozen-model construction remains subject to
the one-request-to-one-file rule.

### Target frozen download and resolved-stage models

Runner-owned download execution moves implementation identity and parameter
identity out of the common stage base. The target frozen models are:

```python
class BaseSpec(ProtocolModel):
    kind: str
    schema_version: Literal[1] = 1
    environment: EnvironmentSpec | None = None
    metric_ids: tuple[MetricId, ...] = ()
    artifacts: dict[ArtifactName, ArtifactSpec] = Field(min_length=1)


class ParameterizedSpec(BaseSpec):
    implementation: StageImplementationRef
    parameter_model: ParameterModelRef


class DownloadSpec(BaseSpec):
    kind: Literal["download"] = "download"
    inputs: dict[InputName, HttpRequestSpec] = Field(min_length=1)
    transport: HttpTransportSpec
    policy: HttpRetrievalPolicy


class InternalSpec(ParameterizedSpec):
    inputs: dict[InputName, InputRef] = Field(min_length=1)


ParameterizedStageSpec = BuildSpec | EmbedSpec | TrainSpec | EvaluateSpec


Spec = Annotated[
    DownloadSpec | ParameterizedStageSpec,
    Field(discriminator="kind"),
]
```

`BaseSpec.validate_artifact_paths()` retains metric, artifact-category,
reserved-name, and artifact-overlap checks. The implementation-path collision
check moves to `ParameterizedSpec`, the class that owns `implementation`.
`DownloadSpec` drops `parameter_model` and `params`.

The target resolved hierarchy separates runner-owned download evidence from
project-callable invocation evidence:

```python
class ResolvedBaseSpec(ProtocolModel):
    schema_version: Literal[1] = 1
    kind: str
    spec: BaseSpec
    environment: ResolvedEnvironment
    execution_context: ExecutionContext
    artifacts: dict[ArtifactName, ResolvedArtifact] = Field(min_length=1)
    completed_at: AwareDatetime


class ResolvedParameterizedSpec(ResolvedBaseSpec):
    spec: ParameterizedSpec
    source: ResolvedGitFileRef
    startup: ProcessStartupReceipt
    invocation: ResolvedStageInvocationRef
    command: tuple[str, ...] = Field(min_length=1)


class ResolvedDownloadSpec(ResolvedBaseSpec):
    kind: Literal["download"] = "download"
    spec: DownloadSpec
    retrievals: dict[InputName, ResolvedHttpRetrieval]


class ResolvedInternalSpec(ResolvedParameterizedSpec):
    spec: InternalSpec
    inputs: dict[InputName, ResolvedInputRef]
```

`ResolvedDownloadSpec` records the environment and execution context of the
VIPER process that invoked the transport. Each `ResolvedHttpRetrieval` records
the selected transport, request, response, body identity, and timestamps.
`ResolvedParameterizedSpec` retains the project source, process startup,
invocation receipt, and child-process command used by build, embed, train, and
evaluate stages.

When VIPER creates an `ArtifactPointer`, it publishes the pointer at the
selected storage destination. The frozen input stores the pointer's SHA-256
digest, byte count, and storage location:

```python
class ResolvedArtifactPointerRef(ResolvedFileRef):
    kind: Literal["artifact_pointer"] = "artifact_pointer"


class StoredInputRef(ProtocolModel):
    kind: Literal["stored"] = "stored"
    pointer: ResolvedArtifactPointerRef
    path: RepoRelPath
    data_role: DataRole


class ResolvedStoredInputRef(ProtocolModel):
    kind: Literal["stored"] = "stored"
    pointer: ResolvedArtifactPointerRef
```

`ResolvedArtifactPointerRef.stored_at` is a `StorageRef`. Local publication
stores a `LocalFileRef` there. Cloud publication stores a
`ViperCloudFileRef`. The `StoredInputRef` validator checks
`pointer.stored_at.path` against the required pointer path. It also checks the
path where VIPER will place the selected artifact.

The active-to-target field changes are:

| Active field | Target field | Reason |
| --- | --- | --- |
| `StoredInputRef.pointer: ArtifactPointerRef` | `StoredInputRef.pointer: ResolvedArtifactPointerRef` | Automatic freezing needs an exact pointer reference before a Git commit exists. |
| `ResolvedArtifactPointerRef.stored_at: ArtifactPointerRef` | Inherited `ResolvedFileRef.stored_at: StorageRef` | The generated pointer records the local or cloud destination that received its immutable bytes. |
| `ResolvedStoredInputRef.pointer: ResolvedArtifactPointerRef` | Retain | The resolved stage records the exact pointer selected by the frozen input. |

Explicit harness mode may accept an `ArtifactPointerRef` authored in Git. The
compiler retrieves that file, checks its bytes, and writes the resulting
`ResolvedArtifactPointerRef` into the frozen `StoredInputRef`.

The active resolved model places `source`, `startup`, `invocation`, and
`command` on `ResolvedBaseSpec`. The target moves those four fields to
`ResolvedParameterizedSpec`. Verification moves the implementation-source and
invocation checks with them. Download verification uses
`ResolvedHttpRetrieval.transport`, the request-response rules, and the shared
artifact-file identity.

`StageDraft.spec.artifacts` contains the path, loader, and data role that will
become `BaseSpec.artifacts`. `StageDraft.artifacts` returns opaque Python
handles that another draft can select as inputs. The public workflow uses the
handle; `StageDraftArtifactRef` remains an authoring-layer type.

The plan mapping assigns stage IDs:

```python
class RunPlanDraft(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    schema_version: Literal[1] = 1
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    benchmark_id: BenchmarkId | None = None
    seed: RNGSeed
    source: GitSource
    environment: EnvironmentSpec
    reproducibility: ReproducibilitySpec
    stages: dict[StageId, StageDraft] = Field(min_length=1)
    estimator: StageDraftArtifactRef
```

The compiler walks `RunPlanDraft.stages` in insertion order. For each
`StageDraftArtifactRef`, it finds the key whose `StageDraft` is the handle's
`producer`. That key becomes `StageArtifactRef.stage_id` and then
`FutureInputRef.producer_stage_id`.

The authoring compiler derives frozen input records from the selected values:

```text
StageDraftArtifactRef whose producer belongs to the active RunPlanDraft
-> StageArtifactRef with the producer's plan key
-> FutureInputRef

FileInputDraft selecting one repository file
-> ExternalInputRef

RunArtifactDraft identifying one artifact in a completed run
-> generated ArtifactPointer
-> publish_resolved_files(repository root, configured destination)
-> ResolvedArtifactPointerRef with a self-locating StorageRef
-> StoredInputRef
```

The input-map key supplies the consumer input name. The selected artifact
declaration supplies its path and data role. The plan key supplies the producer
stage ID. The selected artifact name supplies the producer artifact.

### Target public constructors

The public constructors produce the draft models above:

```python
def file_artifact(
    *,
    path: RepoRelPath,
    loader: Callable[[Path], object],
    data_role: DataRole,
) -> SingleFileArtifactDraft: ...


def file_input(
    *,
    path: RepoRelPath,
    data_role: DataRole,
) -> FileInputDraft: ...


def run_artifact(
    *,
    resolved_run: Path | ResolvedRunRef,
    stage: StageId,
    artifact: ArtifactName,
) -> RunArtifactDraft: ...


def transport(
    implementation: HttpTransportCallable[Any],
    *,
    params: parameters.HttpTransport | None = None,
    executables: tuple[ExternalExecutableSpec, ...] = (),
) -> CustomHttpTransportDraft: ...


def download(
    *,
    inputs: dict[InputName, HttpRequestSpec],
    policy: HttpRetrievalPolicy,
    artifacts: dict[ArtifactName, ArtifactDraft],
    transport: HttpTransportDraft | None = None,
    environment: EnvironmentSpec | None = None,
    metric_ids: tuple[MetricId, ...] = (),
) -> StageDraft: ...


def stage(
    implementation: DecoratedStage,
    *,
    params: parameters.ParameterSet,
    inputs: dict[InputName, StageInputDraft],
    artifacts: dict[ArtifactName, ArtifactDraft],
    environment: EnvironmentSpec | None = None,
    metric_ids: tuple[MetricId, ...] = (),
    evaluation_id: EvaluationId | None = None,
    split_inputs: tuple[InputName, ...] = (),
) -> StageDraft: ...


def plan(
    *,
    run_id: RunId,
    experiment_id: ExperimentId,
    variant_id: VariantId,
    replicate_id: ReplicateId,
    benchmark_id: BenchmarkId | None = None,
    seed: RNGSeed,
    source: GitSource,
    environment: EnvironmentSpec,
    reproducibility: ReproducibilitySpec,
    stages: dict[StageId, StageDraft],
    estimator: StageDraftArtifactRef,
) -> RunPlanDraft: ...


def freeze(plan: RunPlanDraft, *, root: Path = Path.cwd()) -> FrozenPlanFiles: ...
```

`viper.stage()` reads the stage kind and parameter class attached by the
decorator. It rejects a `params` instance whose class differs from the
decorator's class. `viper.download()` constructs `DownloadSpecDraft` directly
because the runner owns download execution. A null authoring transport selects
`BuiltinHttpTransportSpec()`; `DownloadSpecDraft.transport` always contains an
explicit draft after construction.

### Complete proposed authoring example

**Illustrative example:** this program shows the complete target API. The
constructors and shortened decorator names remain proposed until this contract
is implemented.

Create `served/dataset.csv` with these exact 22 bytes:

```csv
feature,label
1,0
2,1
```

Serve the file from the repository root:

```bash
python -m http.server 8000 --directory served
```

The request freezes these expected values:

```text
URL:     http://127.0.0.1:8000/dataset.csv
SHA-256: 81801ff05409c3cddb57bffa4a85667306fa92cd48a8437a9aa937f750a7d7c6
Bytes:   22
```

The complete authoring program is:

```python
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import httpx
from pydantic import Field

import viper
from viper.http import (
    HttpRequestSpec,
    HttpRetrievalError,
    HttpRetrievalPolicy,
    ObservedHttpResponse,
)
from viper.randomness import (
    LegacyNumPyRNGState,
    MainProcessRNGState,
    NumPyRNGState,
    PCG64GeneratorState,
    PCG64InternalState,
    PythonRNGState,
)
from viper.references import GitFileRef, GitSource
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
)
from viper.runtime import (
    LocalEnvironmentSpec,
    NumPyRandomnessSpec,
    ParallelismSpec,
    ReproducibilitySpec,
    TorchDeterminismSpec,
    TorchPrecisionSpec,
    observe_python_environment,
)


REPOSITORY = "https://github.com/example/tiny-viper-model"
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/tiny_http/runs/baseline/{RUN_ID}"

DATASET_PATH = (
    f"{RUN_ROOT}/artifacts/datasets/training_set/dataset.csv"
)
PARAMETERS_PATH = (
    f"{RUN_ROOT}/artifacts/models/tiny_model/parameters.json"
)
RESUME_STATE_PATH = (
    f"{RUN_ROOT}/artifacts/models/tiny_model/resume_state.json"
)


def current_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def load_parameters(path: Path) -> dict[str, float]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_resume_state(path: Path) -> ResumeState:
    return ResumeState.model_validate_json(path.read_text(encoding="utf-8"))


@viper.http_transport(transport_id="project_httpx")
def transfer(
    context: viper.HttpTransportContext[viper.params.HttpTransport],
) -> viper.HttpTransportResult:
    headers = dict(context.request.headers)
    if context.credential is not None:
        headers[context.credential.header] = (
            f"{context.credential.prefix}{context.credential.value}"
        )

    context.destination.parent.mkdir(parents=True, exist_ok=True)
    allowed_response_headers = {
        "content-type",
        "content-encoding",
        "content-length",
        "etag",
        "last-modified",
        "digest",
        "content-digest",
    }

    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        with client.stream(
            context.request.method,
            str(context.request.url),
            headers=headers,
            timeout=context.policy.timeout_seconds,
        ) as response:
            body_bytes = 0
            with context.destination.open("wb") as destination:
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    body_bytes += len(chunk)
                    if body_bytes > context.policy.max_body_bytes:
                        raise HttpRetrievalError(
                            "HTTP body exceeds the policy limit"
                        )
                    destination.write(chunk)

            persisted_headers = {
                name.lower(): value
                for name, value in response.headers.items()
                if name.lower() in allowed_response_headers
            }
            return viper.HttpTransportResult(
                body=context.destination,
                response=ObservedHttpResponse(
                    response_url=str(response.url),
                    status=response.status_code,
                    response_headers=persisted_headers,
                ),
            )


transport = viper.transport(transfer)


download = viper.download(
    inputs={
        "dataset": HttpRequestSpec(
            url="http://127.0.0.1:8000/dataset.csv",
            version="tiny-v1",
            expected_body_sha256=(
                "81801ff05409c3cddb57bffa4a856673"
                "06fa92cd48a8437a9aa937f750a7d7c6"
            ),
            expected_body_bytes=22,
        ),
    },
    transport=transport,
    policy=HttpRetrievalPolicy(
        allowed_schemes=frozenset({"http"}),
        allowed_hosts=frozenset({"127.0.0.1"}),
        allowed_ports=frozenset({8000}),
        accepted_statuses=frozenset({200}),
        max_redirects=0,
        max_body_bytes=1024,
        timeout_seconds=10.0,
    ),
    artifacts={
        "dataset": viper.file_artifact(
            path=DATASET_PATH,
            loader=load_dataset,
            data_role="training",
        ),
    },
)

download_spec = download.spec
assert isinstance(download_spec, viper.DownloadSpecDraft)
assert download_spec.inputs["dataset"].expected_body_bytes == 22
assert download_spec.artifacts["dataset"].path == DATASET_PATH


class TrainParams(viper.params.Train):
    epochs: int = Field(ge=1)
    learning_rate: float = Field(gt=0.0, le=1.0)


@viper.train(params=TrainParams)
def train(context: viper.StageContext[TrainParams]) -> None:
    rows = load_dataset(context.inputs["dataset"])
    weight = 0.0

    for _ in range(context.params.epochs):
        for row in rows:
            feature = float(row["feature"])
            label = float(row["label"])
            prediction = weight * feature
            error = label - prediction
            weight += context.params.learning_rate * error * feature

    weights_path = context.artifacts["parameters"]
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights_path.write_text(
        json.dumps({"weight": weight}, sort_keys=True),
        encoding="utf-8",
    )

    resume_state = ResumeState(
        optimizer_state={"weight": weight},
        main_process_rng=MainProcessRNGState(
            python=PythonRNGState(
                version=3,
                internal_state=(1,),
                gaussian_cache=None,
            ),
            numpy=NumPyRNGState(
                generators={
                    "training": PCG64GeneratorState(
                        state=PCG64InternalState(state=1, inc=1),
                        has_uint32=0,
                        uinteger=0,
                    )
                },
                legacy_global=LegacyNumPyRNGState(
                    keys=(0,) * 624,
                    position=0,
                    has_gaussian=0,
                    cached_gaussian=0.0,
                ),
            ),
            torch_cpu=b"torch-cpu",
            torch_cuda=(),
        ),
        dataloader=DataLoaderResumeState(
            configuration=DataLoaderConfiguration(workers=0),
            state_dict={"num_yielded": len(rows)},
        ),
    )
    resume_state_path = context.artifacts["resume_state"]
    resume_state_path.parent.mkdir(parents=True, exist_ok=True)
    resume_state_path.write_text(
        resume_state.model_dump_json(),
        encoding="utf-8",
    )


training = viper.stage(
    train,
    params=TrainParams(
        epochs=3,
        learning_rate=0.1,
    ),
    inputs={
        "dataset": download.artifacts["dataset"],
    },
    artifacts={
        "parameters": viper.file_artifact(
            path=PARAMETERS_PATH,
            loader=load_parameters,
            data_role="training",
        ),
        "resume_state": viper.file_artifact(
            path=RESUME_STATE_PATH,
            loader=load_resume_state,
            data_role="training",
        ),
    },
)


source_commit = current_commit()
source = GitSource(
    repository=REPOSITORY,
    commit=source_commit,
)
environment = LocalEnvironmentSpec(
    lockfile=GitFileRef(
        repository=REPOSITORY,
        commit=source_commit,
        path="pyproject.toml",
    ),
    python_environment=observe_python_environment(),
)
reproducibility = ReproducibilitySpec(
    determinism=TorchDeterminismSpec(
        deterministic_algorithms=True,
        deterministic_warn_only=False,
        cudnn_deterministic=True,
        cudnn_benchmark=False,
        cublas_workspace_config=":4096:8",
    ),
    precision=TorchPrecisionSpec(
        float32_matmul_precision="highest",
        cudnn_allow_tf32=False,
        autocast_enabled=False,
        autocast_dtype=None,
    ),
    parallelism=ParallelismSpec(
        process_count=1,
        torch_intraop_threads=1,
        torch_interop_threads=1,
        dataloader=DataLoaderConfiguration(workers=0),
    ),
    numpy_randomness=NumPyRandomnessSpec(
        generators={"training": "PCG64"},
        capture_legacy_global=True,
    ),
)


plan = viper.plan(
    run_id=RUN_ID,
    experiment_id="tiny_http",
    variant_id="baseline",
    replicate_id="replicate_01",
    seed=7,
    source=source,
    environment=environment,
    reproducibility=reproducibility,
    stages={
        "download": download,
        "train": training,
    },
    estimator=training.artifacts["parameters"],
)

frozen = viper.freeze(plan)
```

The program contains one custom transport because that extension point belongs
to users who need project-specific HTTP behavior. The transport performs the
network transfer. VIPER enforces the frozen request, response policy,
destination path, body size, SHA-256 digest, and byte count around the returned
`HttpTransportResult`.

The training parameters affect the weight updates inside the nested loops.
`epochs` controls the number of passes, and `learning_rate` scales each update.
The example demonstrates typed execution parameters through the computation
they control.

The runtime path is:

```text
transfer(context)
-> downloads 22 bytes into attempt scratch space

VIPER download executor
-> verifies SHA-256 and byte count
-> publishes the body at DATASET_PATH
-> creates ResolvedHttpRetrieval
-> creates ResolvedSingleFileArtifact
-> gives both records the same SnapshotFileRef

download.artifacts["dataset"]
-> StageDraftArtifactRef(download, "dataset")

plan.stages["download"]
-> assigns the producer stage ID "download"

freeze(plan)
-> converts the handle into FutureInputRef(
       producer_stage_id="download",
       producer_artifact="dataset",
   )

train(context)
-> receives DATASET_PATH through context.inputs["dataset"]
-> uses epochs=3 and learning_rate=0.1 to update one weight
-> writes parameters.json and resume_state.json
```

### Complete local-file and prior-run selections

The complete program uses the same-run handle
`download.artifacts["dataset"]`. The other two input sources use the same
`viper.stage()` call with a different value in its `inputs` map.

A stage can read a local repository file directly:

```python
local_dataset = viper.file_input(
    path="inputs/raw/dataset.csv",
    data_role="training",
)

local_training = viper.stage(
    train,
    params=TrainParams(epochs=3, learning_rate=0.1),
    inputs={"dataset": local_dataset},
    artifacts={
        "parameters": viper.file_artifact(
            path=PARAMETERS_PATH,
            loader=load_parameters,
            data_role="training",
        ),
        "resume_state": viper.file_artifact(
            path=RESUME_STATE_PATH,
            loader=load_resume_state,
            data_role="training",
        ),
    },
)
```

An artifact from a completed run enters through a generated pointer:

```python
prior_dataset = viper.run_artifact(
    resolved_run=Path(
        "experiments/tiny_http/runs/baseline/"
        "01ARZ3NDEKTSV4RRFFQ69G5FAA/resolved.yaml"
    ),
    stage="download",
    artifact="dataset",
)

prior_training = viper.stage(
    train,
    params=TrainParams(epochs=3, learning_rate=0.1),
    inputs={"dataset": prior_dataset},
    artifacts={
        "parameters": viper.file_artifact(
            path=PARAMETERS_PATH,
            loader=load_parameters,
            data_role="training",
        ),
        "resume_state": viper.file_artifact(
            path=RESUME_STATE_PATH,
            loader=load_resume_state,
            data_role="training",
        ),
    },
)
```

Only one of `training`, `local_training`, or `prior_training` belongs in a
given plan because all three examples use the same output paths. Their
decorated callable and artifact declarations stay identical. Freezing changes
only the input record: `FutureInputRef`, `ExternalInputRef`, or
`StoredInputRef`.

### Existing internal results

For a downloaded same-run input, the coordinated target assigns distinct roles
before the authoring compiler creates the consumer reference:

```text
ResolvedDownloadSpec.retrievals["dataset"]
-> ResolvedHttpRetrieval: external-input-root record

ResolvedDownloadSpec.artifacts["dataset"]
-> ResolvedSingleFileArtifact: artifact view

TrainSpec.inputs["dataset"]
-> FutureInputRef: consumer selector
```

The HTTP receipt body and artifact file identify the same `SnapshotFileRef`.
The compiler writes `FutureInputRef`; the selected
`ResolvedSingleFileArtifact` supplies the path and bytes used by training.

The compiler produces the existing types:

```text
source run is the active run
-> FutureInputRef(
       producer_stage_id=<producer stage>,
       producer_artifact=<artifact name>,
   )

source run is a completed prior run
-> ArtifactPointer(
       run=<exact ResolvedRunRef>,
       artifact=<producer stage and artifact name>,
   )
-> serialize_document(pointer)
-> publish_resolved_files(root, destination, {pointer_path: pointer_bytes})
-> ResolvedArtifactPointerRef
-> StoredInputRef
```

`ArtifactPointer` remains the persisted record that joins a prior completed
run to one declared artifact. `RunArtifactDraft` selects that source during
Python authoring; the compiler owns pointer construction and publication.

## 5. Execution

The fixed scenario has one download stage and one training stage in the same
run.

### Same-run path

`viper.freeze()` performs these steps:

```text
StageDraftArtifactRef(producer=download, artifact_name="dataset")
-> find producer key "download" in RunPlanDraft.stages
-> confirm the "download" entry precedes the "train" entry
-> construct FutureInputRef
-> write the frozen TrainSpec
```

When the stage starts, VIPER performs these steps:

```text
FutureInputRef
-> find the completed download stage
-> find dataset in the download stage specification
-> read the artifact's declared path
-> pass that path through StageContext.inputs["dataset"]
```

`FutureInputRef` represents the selection because the source artifact becomes
available inside the active run. The training callable receives the selected
artifact path through `context.inputs["dataset"]`.

### Prior-run path

For an artifact from an earlier run, `viper.freeze()` performs these steps:

```text
RunArtifactDraft(
    resolved_run=Path(
        "experiments/tiny_http/runs/baseline/"
        "01ARZ3NDEKTSV4RRFFQ69G5FAA/resolved.yaml"
    ),
    stage_id="download",
    artifact_name="dataset",
)
-> load and verify that terminal ResolvedRun
-> for Viper Cloud, reject any reachable LocalFileRef or
   LocalStageResultSnapshotRef
-> publish resolved.yaml through publish_resolved_files(root, destination, ...)
-> construct the exact ResolvedRunRef
-> select the declared artifact
-> construct ArtifactPointer
-> serialize and publish the pointer through publish_resolved_files()
-> construct ResolvedArtifactPointerRef
-> construct StoredInputRef with the generated pointer and materialization path
-> write the frozen TrainSpec
```

When the stage starts, VIPER performs these steps:

```text
StoredInputRef.pointer
-> fetch generated ArtifactPointer
-> verify_promoted_artifact()
-> locate the exact dataset files
-> materialize the files at StoredInputRef.path
-> pass the path through StageContext.inputs["dataset"]
```

`viper.freeze()` writes the pointer file. The verifier checks the pointer and
the selected artifact. The training function reads the accepted artifact.

When `RunArtifactDraft.resolved_run` is a `Path`, `viper.freeze()` loads and
checks the terminal run. For a Viper Cloud destination, it then checks the
producer graph before publishing the terminal document. Every reachable
immutable reference must resolve through Viper Cloud, Hugging Face, or Git.
Reaching a `LocalFileRef` or `LocalStageResultSnapshotRef` produces
`storage_graph_unreachable` before pointer publication. Producer migration
remains a separate command that the user runs before freezing.

After that check passes, VIPER publishes the terminal document at the selected
destination and creates `ResolvedRunRef`. When the user supplies an existing
`ResolvedRunRef`, VIPER loads and checks the file named by that reference.

## 6. Persisted evidence

The default mode writes these records:

| Evidence | Writer | Consumer |
| --- | --- | --- |
| Declared artifact path and loader | Stage specification authoring | Stage resolver and artifact verifier |
| Resolved artifact files and byte identities | Completed-stage publication | Artifact loader and verifier |
| `FutureInputRef` | Run-plan compiler | Same-run materialization and verification |
| Generated `ArtifactPointer` | Prior-run input compiler | Pointer verifier and stored-input materializer |
| `ResolvedArtifactPointerRef` | Prior-run input compiler | Frozen `StoredInputRef` and resolved-stage publication |
| `StoredInputRef` | Run-plan compiler | Input materialization and resolved-stage publication |

The compiler derives `category` and `entity_id` from the selected artifact's
declared path. It then computes:

```text
selection_name
= <input_name>_<artifact_name>_<resolved_run_sha256>

pointer_path
= inputs/<category>/<entity_id>/<selection_name>.pointer.yaml
```

For an input and artifact both named `dataset`, the pointer path is:

```text
inputs/datasets/training_set/
dataset_dataset_<resolved_run_sha256>.pointer.yaml
```

The displayed lines form one path. VIPER replaces `<resolved_run_sha256>` with
the 64-character value in `ResolvedRunRef.sha256`. A single-file artifact uses
a sibling directory named `selection_name`, followed by the source filename. A
bundle uses the sibling directory itself.

## 7. Verification

The following checks cover each generated reference.

### `input.source.exists`

`viper.freeze()` looks for the selected stage and artifact. It searches the
current plan or the selected earlier run. A missing stage or artifact stops
freezing.

### `input.source.order`

For a same-run source, the producer stage appears earlier than the consuming
stage. The compiler emits `FutureInputRef` only after this ordering check.

### `input.pointer.identity`

For a prior-run source, the generated `ArtifactPointer.run` identifies the
exact terminal `ResolvedRun`, and `ArtifactPointer.artifact` identifies the
declared producer stage and artifact name.

### `input.pointer.provenance`

`verify_promoted_artifact()` follows the pointer through the resolved run,
successful attempt, selected stage, loaded stage specification, and declared
artifact files. It rejects a missing stage, undeclared artifact, invalid run,
or failed required benchmark.
See [`src/viper/verification.py`](../../src/viper/verification.py).

### `input.bytes`

The materializer checks the resolved file identities already recorded for the
artifact. The consumer receives the path only after the selected files pass
those checks.

## 8. Default mode and harness mode

### Default mode

**Proposed:** The default mode keeps pointer creation inside the authoring and
freezing path. The user controls the four project stage decorators, typed
parameters, artifact declarations, input names, and stage code. VIPER controls
download execution, the internal reference type, and the generated pointer
document.

Users can choose an input in three ways:

```text
viper.file_input(path="inputs/raw/dataset.csv", data_role="training")
-> compiler writes ExternalInputRef
-> context.inputs["dataset"]

download.artifacts["dataset"]
-> training.inputs["dataset"]
-> compiler writes FutureInputRef
-> context.inputs["dataset"]

viper.run_artifact(
    resolved_run=Path(
        "experiments/tiny_http/runs/baseline/"
        "01ARZ3NDEKTSV4RRFFQ69G5FAA/resolved.yaml"
    ),
    stage="download",
    artifact="dataset",
)
-> compiler stores ArtifactPointer and writes StoredInputRef
-> context.inputs["dataset"]
```

### Harness mode

**Deferred:** Harness mode makes promotion an explicit user action. The user
selects an artifact and publishes a named pointer under the project-root
`inputs/` directory. Later runs consume that named selection.

Harness mode may add a policy such as:

```text
automatic capture of declared outputs remains enabled
explicit promotion writes inputs/<category>/<entity>/<selection>.pointer.yaml
```

Harness mode changes pointer visibility and promotion authority. Default-mode
artifact byte recording, run verification, and stage-context paths continue
unchanged. This mode requires a separate contract for command syntax, naming,
overwrite rules, and review ownership.

## 9. Propagation

| Surface | Required change | Acceptance condition |
| --- | --- | --- |
| Public stage API | Add `@viper.build`, `@viper.embed`, `@viper.train`, and `@viper.evaluate`; use `params=` for each parameter class; retain `StageContext` | The complete example constructs and freezes the plan through the target API |
| Parameter namespace | Export `viper.params` as the concise public parameter namespace | `TrainParams` subclasses `viper.params.Train` |
| Download API | Add runner-owned `viper.download()` and remove the project download callable from the target contract | A download draft contains request, transport, policy, environment, metrics, and artifacts; project implementation and stage parameters belong to the other stage drafts |
| Transport API | Make the `@viper.http_transport` parameter class and `viper.transport()` parameter instance optional | The example freezes and invokes `project_httpx` through the base transport parameters |
| Artifact API | Add `viper.file_artifact()` and callable-backed artifact drafts | Freezing converts each loader callable into an exact `ArtifactLoaderRef` |
| Authoring model | Replace `StageDraft.stage_id` and `spec_source` with `spec`; add `StageSpecDraft`, `FileInputDraft`, `RunArtifactDraft`, and artifact-handle access through `StageDraft.artifacts` | A stage input accepts a local file, same-run artifact, or prior-run artifact draft |
| Plan model | Change `RunPlanDraft.stages` from a tuple to `dict[StageId, StageDraft]` | Plan keys become the only source of stage IDs |
| `freeze_run_plan()` | Resolve each artifact handle to `FutureInputRef` or generated `StoredInputRef` | Frozen specs contain the correct internal reference |
| Pointer writer | Serialize prior-run `ArtifactPointer` documents and publish them through the configured independent-file publisher | `StoredInputRef.pointer` carries a digest-bearing `LocalFileRef` or `ViperCloudFileRef` |
| Storage publication | Publish local-root captures, generated pointer files, stage snapshots, and terminal runs at their creation boundaries | Every record carries the storage reference required for retrieval |
| Stage validators | Validate source existence, stage order, roles, and materialization paths | Invalid declarations fail during freezing |
| Runtime resolution | Reuse existing `FutureInputRef` and `StoredInputRef` materialization | `StageContext.inputs` receives the expected path |
| Verification | Reuse `verify_promoted_artifact()` and existing file-identity checks | Tampered source run or artifact fails verification |
| Persisted schema | Change `StoredInputRef.pointer` to `ResolvedArtifactPointerRef` and broaden that reference's storage location to `StorageRef` | Default pointers avoid a Git-commit cycle and remain remotely retrievable |
| Resolved download schema | Move project-invocation fields from `ResolvedBaseSpec` to `ResolvedParameterizedSpec` | `ResolvedDownloadSpec` contains runner environment, execution context, retrieval evidence, and artifacts |
| Download runtime | Execute transport invocation, verification, publication, and artifact resolution in the runner | A successful request creates matching retrieval and artifact records in the attempt process |
| Tests | Add same-run and prior-run acceptance cases plus one severed connector | Tests prove the full authoring-to-consumption path |
| Legacy cleanup | Replace `@viper.*_stage`, `parameter_model=`, stage-constructor `stage_id=`, tuple stage plans, the download callable, and required empty transport parameter classes in tests, fixtures, project scaffolding, and docs | Repository search finds each old form only in migration notes that name its replacement |
| Documentation | Publish the complete authoring example after its API and acceptance case pass | README presents the user workflow while pointer construction stays inside VIPER |

### Legacy cleanup dispositions

Each superseded path leaves in the same implementation increment as its
replacement:

| Active symbol or behavior | Disposition | Target owner |
| --- | --- | --- |
| `download_stage()` and generated `@viper.download_stage` callables | Delete | `viper.download()` constructs the runner-owned draft. |
| `DownloadContext` and `HttpRetrievalHandle` | Delete | The runner consumes `HttpTransportResult` and writes `ResolvedHttpRetrieval`. |
| `parameters.Download` | Delete | Runner-owned `DownloadSpec` uses request, policy, and transport fields. |
| `StageContextBinding.retrievals` and `HttpRetrievalContextBinding` | Delete | The runner consumes retrieval results directly. |
| `execute_stage_process(..., retrievals=...)` | Replace | `_execute_attempt()` invokes the transport and resolves download artifacts directly. |
| `BaseSpec.implementation` | Move | `ParameterizedSpec.implementation` owns project-stage source identity. |
| `ResolvedBaseSpec.source`, `startup`, `invocation`, and `command` | Move | `ResolvedParameterizedSpec` owns project-stage process evidence. |
| Download-stage `StageInvocationReceipt` fixtures | Delete | Successful requests use `ResolvedHttpRetrieval`; failed download attempts use the attempt journal and raised error. |
| `@viper.build_stage`, `@viper.embed_stage`, `@viper.train_stage`, and `@viper.evaluate_stage` | Replace | `@viper.build`, `@viper.embed`, `@viper.train`, and `@viper.evaluate` use `params=`. |
| `StageDraft.stage_id` and tuple-valued `RunPlanDraft.stages` | Replace | `RunPlanDraft.stages` mapping keys own stage IDs. |
| Direct `ExternalInputRef` construction in public authoring | Replace | `viper.file_input()` creates `FileInputDraft`; freezing writes `ExternalInputRef`. |
| Proposed prior-run construction through `RunArtifactRef` | Replace | `viper.run_artifact()` creates `RunArtifactDraft`; freezing verifies the completed run and writes the pointer. |
| `StoredInputRef.pointer: ArtifactPointerRef` | Replace | Use `ResolvedArtifactPointerRef` so the frozen input carries pointer byte identity and a local, Git, or remote storage location. |
| `ResolvedArtifactPointerRef.stored_at: ArtifactPointerRef` | Replace | Inherit `StorageRef` from `ResolvedFileRef`; retain canonical pointer-path validation in `StoredInputRef`. |
| YAML `spec_source` authoring and generated draft-stage files | Replace | `StageDraft.spec` holds the Python-authored declaration until freezing writes canonical YAML. |
| Required `@viper.http_transport(parameter_model=...)` | Replace | `@viper.http_transport(params=...)` defaults to `viper.params.HttpTransport`. |
| Required empty transport parameter instances | Delete | `viper.transport(transfer)` constructs the base parameter instance. |
| Direct `SingleFileArtifactSpec` construction in public examples | Replace | `viper.file_artifact()` accepts the loader callable and freezing writes `ArtifactLoaderRef`. |
| Existing protocol YAML, CLI parsing, verifier reconstruction, tests, fixtures, and project scaffolding that construct the old shapes | Replace | Each consumer parses or constructs the target frozen and resolved models. |

## 10. Acceptance cases

### Local file and training

The acceptance fixture creates `inputs/raw/dataset.csv` and selects it through
`viper.file_input()`.

```text
freeze the run plan
-> compiler writes ExternalInputRef into TrainSpec.inputs["dataset"]
-> execute train
-> runner publishes the captured source bytes at the configured destination
-> train receives inputs/raw/dataset.csv
-> resolved train record contains ResolvedExternalInputRef
```

The test asserts the captured SHA-256 digest and byte count, the source path
received by training, and local-root verification. Changing the captured store
bytes triggers `input.local_root_identity`.

### Same-run download and training

The acceptance fixture defines a runner-owned download draft with a declared
`dataset` artifact and a decorated training stage with `TrainParams`.

```text
freeze the run plan
-> plan mapping assigns "download" and "train"
-> compiler identifies download.dataset
-> compiler writes FutureInputRef into TrainSpec.inputs["dataset"]
-> execute download
-> execute train
-> train receives context.inputs["dataset"]
-> resolved train record contains ResolvedFutureInputRef
```

The test asserts that the frozen training input selects the download stage and
`dataset`, and that the training callable receives the materialized path.

### Prior-run download and training

The acceptance fixture freezes and completes a download run first. A second
run declares that completed artifact as its training input.

```text
freeze the training plan
-> compiler creates one ArtifactPointer for download.dataset
-> compiler writes StoredInputRef into the frozen TrainSpec
-> pointer verification follows the source run and artifact
-> training receives the verified materialized path
```

The test asserts that the pointer selects the intended run, stage, and artifact
and that the resolved training input records the generated pointer reference.

### Targeted rejection

After freezing a prior-run input, change
`ArtifactPointer.artifact.artifact_name` to a name absent from the selected
producer stage. The verifier must reject the input under
`input.pointer.provenance`.

This rejection severs the connector under review: the generated pointer names
an artifact absent from the declared producer stage, so the verifier rejects
the selection.

## 11. Implementation order

This implementation starts after the runner-owned download and local-root
increments defined by the first two contracts in the dependency order in
[`external-input-roots.md`](external-input-roots.md#10-propagation-and-implementation-order).

### Phase 1. Define the Python authoring models

- [ ] Replace `StageDraft.spec_source` with `StageDraft.spec`.
- [ ] Remove `StageDraft.stage_id`; change `RunPlanDraft.stages` to
      `dict[StageId, StageDraft]`.
- [ ] Define the complete `StageSpecDraft` variants for the five stage kinds.
- [ ] Expose one `StageDraftArtifactRef` per declared artifact through
      `StageDraft.artifacts`.
- [ ] Add callable-backed artifact and transport drafts.
- [ ] Add `FileInputDraft`, `RunArtifactDraft`, and the `StageInputDraft`
      authoring union.
- [ ] Add `viper.params`, the shortened project-stage decorators, and the
      `viper.stage()`, `viper.download()`, `viper.transport()`,
      `viper.file_artifact()`, `viper.file_input()`, `viper.run_artifact()`,
      `viper.plan()`, and `viper.freeze()` constructors.
- [ ] Add focused model tests.

**Commit boundary:** Python constructs a complete run-plan draft with local,
same-run, or prior-run input selections. The compiler-facing draft models are
complete.

### Phase 2. Expose runner-owned download through Python authoring

- [ ] Make `viper.download()` construct `DownloadSpecDraft` directly.
- [ ] Select `BuiltinHttpTransportSpec()` when the author omits `transport=`.
- [ ] Convert a `CustomHttpTransportDraft` into the existing frozen transport
      records when the author supplies a custom transport.
- [ ] Replace generated project download callables with `viper.download()`.

**Commit boundary:** Python authoring creates a valid runner-owned download
stage through either the built-in transport or one decorated custom transport.

### Phase 3. Compile local and same-run inputs

- [ ] Convert each `FileInputDraft` into `ExternalInputRef` with one
      `LocalSource` and the declared data role.
- [ ] Map each `StageDraftArtifactRef.producer` to its key in
      `RunPlanDraft.stages` and construct `FutureInputRef`.
- [ ] Capture local-root bytes, retain the selected source path, and add the
      local-root verifier.
- [ ] Preserve the existing `TrainSpec` and `InternalSpec` validators.
- [ ] Add the local-file-to-training acceptance case.
- [ ] Add the complete custom-transport download-to-training acceptance case.

**Commit boundary:** a frozen plan connects a local file or download artifact
to training while the compiler owns the `ExternalInputRef` and
`FutureInputRef` syntax.

### Phase 4. Generate prior-run pointers

- [ ] Change `StoredInputRef.pointer` to `ResolvedArtifactPointerRef` and let
      that reference inherit `StorageRef`.
- [ ] Implement and validate the full-digest generated-pointer path rule.
- [ ] Load and verify the selected terminal `ResolvedRun`.
- [ ] Construct `ArtifactPointer` from the selected run and artifact.
- [ ] Serialize the pointer and publish it through
      `publish_resolved_files(root, destination, ...)`.
- [ ] Construct `ResolvedArtifactPointerRef` and `StoredInputRef` for the
      consumer.
- [ ] Add the prior-run acceptance case and targeted rejection.

**Commit boundary:** a later run consumes a prior VIPER artifact through a
compiler-generated pointer.

### Phase 5. Update user documentation

- [ ] Replace the README stage example with the complete proposed authoring
      example after the target API passes its acceptance case.
- [ ] Document plan-owned stage IDs and automatic input resolution in the
      getting-started guide.
- [ ] Document pointer files as generated protocol evidence.
- [ ] Add the harness-mode design as a separate proposed contract.

**Commit boundary:** the public documentation describes the user workflow and
the internal protocol separately.

### Deferred harness mode

- [ ] Define explicit promotion command or authoring API.
- [ ] Define project-root `inputs/` ownership and naming.
- [ ] Define overwrite and review rules.
- [ ] Define how explicit promotion interacts with automatically generated
      pointers.

## 12. Verdict

**Proposed decision:** implement automatic pointer generation beneath the
Python authoring API defined in this contract.

The runtime already publishes artifacts, checks pointers, and places input
files where stages can read them. The proposed API adds the missing step:
`viper.freeze()` chooses and writes `FutureInputRef` or `StoredInputRef` for the
user.

Implementation starts with the draft models and the runner-owned download
stage. The next step handles local files and artifacts from the same run. The
last step writes pointers for artifacts from earlier runs. A separate contract
will define harness mode under the project-root `inputs/` directory.

[`remote-storage.md`](remote-storage.md) defines where VIPER stores pointers and
captured files. Each `StorageRef` tells VIPER where to retrieve its file. The
same Python authoring API works with local storage and Viper Cloud.

## Implementation sources

- [Stage models and decorators](../../src/viper/stages.py)
- [Run-plan authoring](../../src/viper/authoring.py)
- [Artifact and pointer models](../../src/viper/artifacts.py)
- [Pointer and artifact verification](../../src/viper/verification.py)
- [Input materialization](../../src/viper/execution/_materialization.py)
- [Pointer acceptance construction](../../tests/test_generated_project_acceptance.py)
- [Public stage example](../../README.md#define-a-stage)
