# How VIPER works

VIPER runs a frozen machine-learning experiment and checks the evidence produced
by that execution. A frozen plan identifies the source revision, stage
implementations, parameters, inputs, environment, reproducibility controls, and
expected outputs. The completed run records what happened. Verification joins
the plan to the recorded evidence before accepting the result.

## The verification chain

One run follows this sequence:

```text
authored experiment
        |
        v
frozen RunSpec and stage specifications
        |
        v
preflight checks on the selected host
        |
        v
typed stage execution in controlled child processes
        |
        v
immutable stage and attempt evidence
        |
        v
terminal verification
```

Each arrow has an implementation boundary and persisted evidence. The
[formal protocol](../reference/protocol.md) defines the documents. The
[public API](../reference/api.md) defines the operations that create and check
them.

## 1. Project code declares stages

A project owns its scientific code and parameter classes. VIPER supplies stage
decorators and typed contexts:

```python
import viper
from my_project.training import train_model


class TrainParameters(viper.parameters.Train):
    epochs: int
    learning_rate: float


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    dataset_path = context.inputs["dataset"]
    weights_path = context.artifacts["parameters"]
    train_model(
        dataset_path=dataset_path,
        weights_path=weights_path,
        epochs=context.params.epochs,
        learning_rate=context.params.learning_rate,
    )
```

The decorator binds `train` to the training-stage category and
`TrainParameters`. The callable receives one `StageContext` containing the
validated parameters, materialized input paths, writable artifact paths, live
metric handles, named NumPy generators, and active run identity. The
[stage module](../../src/viper/stages.py) owns this interface.
`train_model` belongs to the project and performs the scientific computation.
The `parameters` artifact key is VIPER's required slot for trained model state.
The project uses `weights_path` as the local name for that destination.

The project can use its ordinary Python entrypoint:

```python
if __name__ == "__main__":
    viper.run(train)
```

```bash
python train.py --run experiments/example/runs/run-001/spec.yaml --stage train
```

The installed command invokes the same coordinator:

```bash
viper run experiments/example/runs/run-001/spec.yaml
```

## 2. Freezing fixes the computation

An experiment selects a variant and replicate. The variant supplies stage
parameters. The replicate supplies the run's global seed. `freeze_run_plan()`
then writes one `RunSpec` and the exact stage specifications it references.

For each project-owned implementation, freezing records its repository-relative
path, top-level symbol, SHA-256 digest, and byte count. The source commit fixes
the repository state that owns those bytes. A later edit creates a new plan
identity.

```text
source commit
+ stage callable identity
+ parameter-class identity
+ stage parameters
+ inputs and outputs
+ environment and controls
        |
        v
frozen RunSpec
```

The [authoring module](../../src/viper/authoring.py) constructs the frozen
documents. The [run module](../../src/viper/runs.py) and
[stage module](../../src/viper/stages.py) define their schemas.

## 3. Preflight checks the selected host

Preflight loads the complete plan before execution. It checks the Git source,
implementation bytes, parameter classes, metrics, artifact loaders, HTTP
transports, environment requirements, and same-run dependencies. Each result
has a stable check code, status, and message. A failed check stops execution
before a stage starts.

The [preflight module](../../src/viper/preflight.py) owns these checks.

## 4. The coordinator executes typed stage invocations

The coordinator allocates an attempt ID and executes the stages in plan order.
Each stage runs in a child process using the same Python interpreter as the
coordinator. Before project code runs, VIPER applies the global seed, named
NumPy generators, PyTorch determinism settings, floating-point policy, thread
counts, DataLoader configuration, and compute-device selection.

For one training stage, the coordinator performs the equivalent of:

```python
callable = load_verified_callable(stage.implementation)
params = load_and_validate(stage.parameter_model, stage.params)
context = StageContext(
    run_id=run.run_id,
    attempt_id=attempt_id,
    stage_id=stage.stage_id,
    params=params,
    inputs=materialized_inputs,
    artifacts=allocated_outputs,
    metrics=metric_handles,
    numpy_generators=initialized_generators,
)
callable(context)
```

The live `StageContext` contains Python runtime objects. VIPER also persists a
serializable binding that names the same invocation through stable paths and
identities. The [stage executor](../../src/viper/execution/_stage.py)
and [stage worker](../../src/viper/_workers/stages.py) implement this boundary.

## 5. Inputs retain lineage and data-use roles

An internal input comes from a promoted artifact or an earlier stage in the
same run. VIPER verifies the producing evidence before materializing the input
at the path fixed by the consuming stage. The
[materialization module](../../src/viper/materialization.py) performs that
operation.

Every input and output has a data-use role. Training stages can consume
training inputs. Evaluation and benchmark inputs stay outside the training
path. An output inherits the strongest restriction carried by its inputs. The
[verifier](../../src/viper/verification.py) enforces these joins across the
complete plan.

Download stages use frozen HTTP requests. A request fixes the URL, accepted
statuses, expected response byte count, and expected SHA-256 digest. The
selected transport retrieves the body. VIPER checks the response before the
download callable receives it through `DownloadContext`. Projects can register
another transport through `@viper.http_transport` while retaining the same
request and response contract. The [HTTP module](../../src/viper/http.py) owns
this interface.

## 6. Artifacts become immutable evidence

A stage declares each output before execution. A file artifact identifies one
file. A bundle identifies every regular file beneath one declared directory.
Each resolved file records its path, byte count, and SHA-256 digest.

A training checkpoint contains two reserved artifacts:

- `parameters` stores the trained model state, such as learned weights and
  persistent buffers.
- `resume_state` stores the optimizer, random-number-generator, and stateful
  DataLoader state required for exact continuation.

The [artifact module](../../src/viper/artifacts.py) defines artifact identity.
The [resume module](../../src/viper/resume.py) captures and restores training
state.

VIPER publishes stage snapshots and attempt documents beneath the local
content-addressed store. `ResolvedRun` references each canonical attempt file
by path, byte count, and digest. The [storage module](../../src/viper/storage.py)
and [workspace module](../../src/viper/workspace.py) own publication.

## 7. Metrics carry their producing evidence

A project metric is a decorated function or stateful class. `MetricSpec` fixes
its implementation, parameters, dependencies, production mode, and comparison
rule.

Training metrics can write measurements during a stage. Evaluation metrics can
run after the stage from persisted artifacts. A recomputed metric runs in a
dedicated worker from the frozen implementation and verified dependencies. The
verification receipt stores the recomputed value and the worker's execution
evidence. The verifier compares that value with the recorded measurement.

The [metric module](../../src/viper/metrics.py) defines the contract. The
[metric executor](../../src/viper/execution/_metric.py) runs recomputation.

## 8. Attempts preserve success and failure

One frozen plan can have several attempts. VIPER allocates increasing attempt
IDs under a lock and records each state transition in a durable journal. A
successful, failed, cancelled, or preempted attempt publishes
`attempts/<attempt_id>/resolved.yaml`. Failed invocations retain their typed
failure evidence and logs.

`viper retry` appends another attempt to the same plan. Earlier evidence remains
addressable through the terminal `ResolvedRun`. The
[execution package](../../src/viper/execution/) coordinates attempts, and the
[journal module](../../src/viper/journal.py) owns their transition history.

## 9. Verification reconstructs the run

Terminal verification begins with `ResolvedRun`. The verifier retrieves the
frozen plan, stage specifications, canonical attempt files, artifacts,
measurements, and receipts. It checks each reference before using the referenced
value in a later claim.

The accepted result has a connected evidence path:

```text
RunSpec
  -> exact stage specification
  -> verified stage invocation
  -> verified inputs
  -> resolved artifacts and measurements
  -> canonical successful attempt
  -> terminal ResolvedRun
```

`verify_run_result()` returns the connected plan, attempts, stage results, and
measurements after those checks pass. The
[verification module](../../src/viper/verification.py) owns the public
verification operations.

## 10. Benchmarks confirm one frozen evaluation

An evaluation measures one candidate. A benchmark applies one evaluation
definition across candidates and requires an independent confirmation attempt
for each candidate.

`execution.benchmark()` starts a new attempt from the candidate's frozen
`RunSpec`. The benchmark checks artifact parity and applies its metric criteria
to independently recomputed values:

```text
verified candidate attempt
        |
        v
independent attempt from the same RunSpec
        |
        v
trained-model and predictions parity
        |
        v
metric criteria
        |
        v
verified BenchmarkResult
```

Each architecture belongs to its own run plan. One `BenchmarkSpec` can govern
the common evaluation applied to all of them. The
[execution package](../../src/viper/execution/) constructs the result.

## 11. Agents and humans use the same operations

The Python API, CLI, and JSON interface share typed request and result models.
`viper schema` returns a registered JSON Schema. `viper capabilities` lists
the installed operations and execution backends. Inspection operations report
attempt status, plan differences, verified lineage, and verified run
differences.

This interface lets an agent inspect a contract, submit one bounded operation,
and receive a stable failure code. A human can use the same operation through
Python or the terminal. See the [API reference](../reference/api.md).

## 12. Execution environment and scope

VIPER executes inside the host selected by the user. A workstation and an
already provisioned virtual machine use the same commands. For a GCE run, the
plan fixes the boot image, machine type, dependency lockfile, Python
environment, and compute request. The child process records the observed host,
CPU, selected CUDA device, driver, PyTorch CUDA runtime, and cuDNN runtime.

Version `0.1` supports one host process and one selected CUDA device per stage.
Distributed execution requires a future contract for rank topology, per-rank
evidence, collective-library configuration, and distributed checkpoint
identity. The [runtime module](../../src/viper/runtime.py) defines the current
host and compute evidence.

Project-owned stage callables, transports, metrics, and artifact loaders execute
as trusted code. VIPER verifies their source identity and controls their
invocation. Adversarial code isolation remains outside the `0.1` contract.

Typed stage invocation proves that the validated parameter object reached the
selected callable. Each project tests how its callable uses individual fields.
Epoch-completion receipts and an optional heightened-oversight policy remain
future work.

VIPER `0.1.0a1` is available from PyPI. Its
[release report](../releases/0.1.0a1.md) records the source tag, distribution
digests, clean installation checks, generated-project execution, and live
NVIDIA L4 run.
