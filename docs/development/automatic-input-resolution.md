# Automatic artifact capture and input resolution

VIPER should let a project keep its decorator-based stage definitions and
typed parameter classes while VIPER creates the internal artifact references
required to connect produced data to later stages. This contract defines the
default workflow for one run and records the separate design boundary for a
future explicit harness mode.

## 1. Status

**Contract status:** proposed authoring and freezing change; implementation
pending.

**Current:** Project code defines stages with `@viper.download_stage`,
`@viper.train_stage`, and a subclass of `viper.parameters.Train`. The stage
callable receives a `StageContext`; the callable reads materialized input paths
from `context.inputs` and writes declared outputs through `context.artifacts`.
See [`README.md`](../../README.md#define-a-stage) and
[`src/viper/stages.py`](../../src/viper/stages.py).

**Current:** `DownloadSpec` accepts HTTP request inputs, while `TrainSpec`
accepts an `InputRef` union containing `ExternalInputRef`, `StoredInputRef`, and
`FutureInputRef`. The user-authored frozen stage specification therefore names
the internal relationship between a training input and its source.
See [`src/viper/stages.py`](../../src/viper/stages.py).

**Proposed:** The user keeps the decorator and typed-parameter workflow. The
authoring layer accepts a project-level artifact input declaration and converts
that declaration into `FutureInputRef` for a same-run source or `StoredInputRef`
plus an internally written `ArtifactPointer` for a completed prior run.

The proposal changes the authoring boundary. It keeps the runtime context,
artifact schemas, verification rules, and physical storage contract stable.

## 2. Required claim

When a user declares a VIPER-produced dataset as the input to a decorated
training stage, VIPER records the dataset's producing stage and exact artifact
identity, selects the correct internal reference, and supplies the verified
dataset path through `StageContext.inputs`.

The user writes the stage decorator, the `TypedParameters` class, and the
training function. VIPER writes the internal pointer or same-run reference
during plan authoring and freezing.

## 3. Current gap

The fixed scenario is:

```text
download a dataset
-> declare the downloaded dataset as a stage artifact
-> train a model on that dataset
```

The current path is:

```text
DownloadSpec.artifacts["training_dataset"]
-> completed download stage records the resolved artifact
-> TrainSpec.inputs["dataset"]
-> user selects FutureInputRef or StoredInputRef
-> runtime materializes the input
-> train(context) reads context.inputs["dataset"]
```

**Inspected:** `FutureInputRef` carries `producer_stage_id` and
`producer_artifact` for an earlier stage in the same run.
[`src/viper/stages.py`](../../src/viper/stages.py)

**Inspected:** `StoredInputRef` carries an `ArtifactPointerRef`, a
materialization path, and a data role for an artifact from a completed run.
[`src/viper/stages.py`](../../src/viper/stages.py)

**Inspected:** `freeze_run_plan()` validates authored stage specifications and
writes frozen stage and run files. It currently preserves the input reference
already present in the stage specification. Pointer-document construction
belongs to the proposed authoring operation.
[`src/viper/authoring.py`](../../src/viper/authoring.py)

**Inspected:** The execution layer already follows a `StoredInputRef` pointer,
calls `verify_promoted_artifact()`, materializes the verified files, and passes
the resulting path to the stage context.
[`src/viper/execution/_materialization.py`](../../src/viper/execution/_materialization.py)

The missing connector is the authoring operation that takes a user-level
artifact input declaration and creates the internal reference consumed by the
existing planner, verifier, and materializer.

The current system therefore supports the runtime operation while exposing its
protocol representation at the authoring boundary.

## 4. Contract models

### Existing public stage interface

The proposal preserves this project-facing interface:

```python
class TrainParameters(viper.parameters.Train):
    epochs: int
    learning_rate: float


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    dataset = context.inputs["dataset"]
    weights = context.artifacts["parameters"]
    train_model(dataset, weights, context.params.epochs)
```

`TrainParameters` validates the values in `TrainSpec.params`. The decorator
binds the callable to the `train` stage kind and parameter model. The executor
continues to pass a `Path` through `context.inputs["dataset"]`.

### Proposed authoring input

**Proposed:** Add one authoring-level input declaration whose purpose is to
select a produced artifact while keeping the persisted pointer format inside
VIPER.

The declaration carries these values:

```text
input name       -> the key exposed through context.inputs
source run       -> current run or one completed prior run
producer stage   -> the stage that declared the artifact
producer artifact -> the declared artifact name
path             -> the path where the consumer receives the bytes
data role        -> the role expected by the consumer
```

The exact serialized name and syntax for this authoring-level declaration are
an implementation decision. The declaration must remain separate from
`ArtifactPointer`, because `ArtifactPointer` is the persisted verification
record and the authoring declaration is the user's selection.

### Existing internal results

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
-> ArtifactPointerRef at the generated internal pointer path
-> StoredInputRef(pointer=<pointer ref>, path=<materialization path>, ...)
```

`ArtifactPointer` remains the persisted record that joins a prior completed
run to one declared artifact. The user-facing declaration selects the source;
the compiler owns pointer construction and publication.

## 5. Execution

The fixed scenario has one download stage and one training stage in the same
run.

### Same-run path

The authoring layer performs this operation:

```text
user's artifact input declaration
-> identify source stage download
-> identify source artifact training_dataset
-> confirm download precedes train in the run plan
-> construct FutureInputRef
-> write the frozen TrainSpec
```

The existing materialization layer then performs this operation:

```text
FutureInputRef
-> find the completed download stage
-> read the declared training_dataset artifact
-> use its resolved files
-> write the consumer path
-> pass that path through StageContext.inputs["dataset"]
```

`FutureInputRef` remains the correct representation because the source artifact
becomes available inside the active run. The user sees the same decorated
`train(context)` function and the same `Path` value.

### Prior-run path

When the source run completed earlier, the authoring layer performs this
operation:

```text
user's artifact input declaration
-> identify the completed source run
-> load and verify its terminal ResolvedRun
-> select download.training_dataset
-> construct ArtifactPointer
-> write the pointer under the internal project input area
-> construct StoredInputRef pointing at that generated pointer
-> write the frozen TrainSpec
```

The existing runtime then performs this operation:

```text
StoredInputRef.pointer
-> fetch generated ArtifactPointer
-> verify_promoted_artifact()
-> locate the exact training_dataset files
-> materialize the files at StoredInputRef.path
-> pass the path through StageContext.inputs["dataset"]
```

The authoring layer owns the generated pointer file. The verifier owns the
decision to accept the selected artifact. The stage callable owns the model
training operation.

## 6. Persisted evidence

The default mode preserves the existing durable evidence:

| Evidence | Writer | Consumer |
| --- | --- | --- |
| Declared artifact path and loader | Stage specification authoring | Stage resolver and artifact verifier |
| Resolved artifact files and byte identities | Completed-stage publication | Artifact loader and verifier |
| `FutureInputRef` | Run-plan compiler | Same-run materialization and verification |
| Generated `ArtifactPointer` | Prior-run input compiler | Pointer verifier and stored-input materializer |
| `StoredInputRef` | Run-plan compiler | Input materialization and resolved-stage publication |

The generated pointer uses the existing canonical pointer path:

```text
inputs/<category>/<entity_id>/<selection_name>.pointer.yaml
```

The default compiler must choose deterministic names from the consuming input
and source artifact, or store the generated pointer in an internal generated
area with a deterministic identity. The naming rule is an open implementation
decision because the current `ArtifactPointerRef` validator requires the
category, entity ID, and selection name.

## 7. Verification

The proposal preserves the existing verification boundary.

### `input.source.exists`

The authoring layer finds the selected source stage and artifact in the active
run plan or the selected completed prior run. A missing stage or artifact makes
plan freezing fail before execution.

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
freezing path. The user controls the stage decorators, typed parameters,
artifact declarations, input names, and stage code. VIPER controls the internal
reference type and generated pointer document.

The user-facing path remains:

```text
decorated stage
-> typed parameters
-> declared input
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
| Public stage API | Preserve `@viper.*_stage`, `TypedParameters`, and `StageContext` | Existing README stage code remains valid |
| Authoring model | Add the user-level produced-artifact input declaration | A declaration identifies source run, stage, artifact, path, and role |
| `freeze_run_plan()` | Resolve each declaration to `FutureInputRef` or generated `StoredInputRef` | Frozen specs contain the correct internal reference |
| Pointer writer | Serialize and publish prior-run `ArtifactPointer` documents | Pointer bytes are deterministic and canonical |
| Stage validators | Validate source existence, stage order, roles, and materialization paths | Invalid declarations fail during freezing |
| Runtime resolution | Reuse existing `FutureInputRef` and `StoredInputRef` materialization | `StageContext.inputs` receives the expected path |
| Verification | Reuse `verify_promoted_artifact()` and existing file-identity checks | Tampered source run or artifact fails verification |
| Persisted schema | Preserve `ArtifactPointer`, `StoredInputRef`, and resolved input schemas | Existing records remain readable |
| Tests | Add same-run and prior-run acceptance cases plus one severed connector | Tests prove the full authoring-to-consumption path |
| Documentation | Keep decorator and typed-parameter examples user-facing | README presents the user workflow while pointer construction stays inside VIPER |

## 10. Acceptance cases

### Same-run download and training

The acceptance fixture defines a decorated download stage with a declared
`training_dataset` artifact and a decorated training stage with a typed
parameter model.

```text
freeze the run plan
-> compiler identifies download.training_dataset
-> compiler writes FutureInputRef into TrainSpec.inputs["dataset"]
-> execute download
-> execute train
-> train receives context.inputs["dataset"]
-> resolved train record contains ResolvedFutureInputRef
```

The test asserts that the frozen training input selects the download stage and
`training_dataset`, and that the training callable receives the materialized
path.

### Prior-run download and training

The acceptance fixture freezes and completes a download run first. A second
run declares that completed artifact as its training input.

```text
freeze the training plan
-> compiler creates one ArtifactPointer for download.training_dataset
-> compiler writes StoredInputRef into the frozen TrainSpec
-> pointer verification follows the source run and artifact
-> training receives the verified materialized path
```

The test asserts that the pointer selects the intended run, stage, and artifact
and that the resolved training input records the generated pointer reference.

### Targeted rejection

Change the source artifact name after the input declaration has been frozen.
The verifier must reject the input under `input.pointer.provenance` because the
selected producer stage declares a different artifact set.

This rejection severs the connector under review: the user-level input
selection resolves to an artifact name absent from the declared producer
stage, so the verifier rejects the selection.

## 11. Implementation order

### Phase 1. Define the authoring declaration

- [ ] Choose the serialized user-level input shape.
- [ ] Add the model and its source-run, producer-stage, producer-artifact, path,
      and data-role fields.
- [ ] Add validation for source existence and same-run stage order.
- [ ] Add focused model tests.

**Commit boundary:** the new declaration parses and rejects invalid source
selections. Existing `FutureInputRef` and `StoredInputRef` behavior remains
unchanged.

### Phase 2. Compile same-run inputs

- [ ] Add the compiler operation that maps a same-run declaration to
      `FutureInputRef`.
- [ ] Preserve the existing `TrainSpec` and `InternalSpec` validators.
- [ ] Add the same-run download-to-training acceptance case.

**Commit boundary:** a frozen plan connects a download artifact to training
while the compiler owns the `FutureInputRef` syntax.

### Phase 3. Generate prior-run pointers

- [ ] Load and verify the selected terminal `ResolvedRun`.
- [ ] Construct `ArtifactPointer` from the selected run and artifact.
- [ ] Write the pointer through the existing deterministic document serializer.
- [ ] Construct `ArtifactPointerRef` and `StoredInputRef` for the consumer.
- [ ] Add the prior-run acceptance case and targeted rejection.

**Commit boundary:** a later run consumes a prior VIPER artifact through a
compiler-generated pointer.

### Phase 4. Update user documentation

- [ ] Keep the decorator and typed-parameter examples unchanged.
- [ ] Document automatic input resolution in the getting-started guide.
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
existing decorator and typed-parameter authoring model.

The current runtime already owns artifact publication, pointer verification,
and input materialization. The missing behavior sits in the authoring layer:
the layer that currently requires the user to select `FutureInputRef` or
`StoredInputRef` directly.

The first implementation should cover same-run resolution, then prior-run
pointer generation. Harness mode should follow as a separate explicit
promotion contract under the project-root `inputs/` directory.

## Implementation sources

- [Stage models and decorators](../../src/viper/stages.py)
- [Run-plan authoring](../../src/viper/authoring.py)
- [Artifact and pointer models](../../src/viper/artifacts.py)
- [Pointer and artifact verification](../../src/viper/verification.py)
- [Input materialization](../../src/viper/execution/_materialization.py)
- [Pointer acceptance construction](../../tests/test_generated_project_acceptance.py)
- [Public stage example](../../README.md#define-a-stage)
