# VIPER: verified execution and provenance for computational experiments

## 1. Executive summary

A computational result depends on more than the function that produced it. The
result also depends on the exact input bytes, source revision, parameters,
runtime environment, randomness controls, and upstream artifacts used during
execution. A conventional training script can save a model and a log while
leaving those dependencies implicit.

VIPER turns those dependencies into a frozen run plan. It executes the plan,
publishes immutable evidence for each attempt, and verifies the completed run
by reconstructing every declared relationship. Project code remains ordinary
Python: users define typed parameter classes, decorate stage callables and
metrics, and invoke the run through Python or the installed command.

VIPER `0.1.0a1` supports trusted single-host execution on a workstation or a
pre-provisioned Google Compute Engine instance. One stage can use the CPU or
one selected CUDA device. The current release candidate has completed local,
installed-wheel, continuous-integration, and live NVIDIA L4 acceptance gates.
Registry publication remains pending owner-supplied package metadata,
credentials, authorization, and tag signing.

## 2. The problem VIPER solves

An experiment plan makes a scientific claim about a future computation. A
completed model provides evidence only when the system can answer
four questions: which plan governed the run, which implementation executed,
which values crossed each stage boundary, and which checks accepted the final
result.

VIPER gives each answer a concrete representation. `RunSpec` fixes one run.
The stage specifications fix the ordered operations. A `RunAttempt` describes
one execution of that plan. Resolved stage files describe the environment,
inputs, outputs, measurements, and invocation evidence observed during that
attempt. `ResolvedRun` references the canonical attempt files and identifies
the successful attempt when one exists. The [run](../src/viper/runs.py) and
[stage](../src/viper/stages.py) modules define these types. VIPER serializes them through the
[canonical document encoder](../src/viper/serialization.py).

The separation between requested and observed values matters. A requested CUDA
model belongs in the plan. The device model, driver, CUDA runtime, and cuDNN
runtime observed by the child process belong in the resolved stage. The
verifier compares the two representations after execution.

## 3. User-facing execution model

VIPER accepts any repository layout because the frozen specifications use
repository-relative paths. A project owns its scientific code, parameter
classes, metrics, and custom artifact loaders. The installed `viper` package
owns authoring, execution, publication, and verification.

The initializer creates one complete example project:

```bash
viper init my-project --package my_project
```

The generated source contains decorated callables for download, build, embed,
train, and evaluate stages, along with parameter classes, a metric, an artifact
loader, and tests. The generated files are ordinary project source. Users can
move or replace them because frozen specifications identify implementations by
repository-relative path and exact bytes. [project_init.py](../src/viper/project_init.py)
implements the initializer.

A training callable has one typed argument:

```python
from pydantic import Field

import viper
import viper


class TrainParameters(viper.parameters.Train):
    epochs: int = Field(gt=0)


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    dataset = context.inputs["dataset"]
    parameters = context.artifacts["parameters"]
    epochs = context.params.epochs
    # Project training code reads dataset and writes parameters.
```

The decorator attaches the stage kind and parameter class to the function.
Freezing resolves that function to a repository-relative file, a top-level
symbol, a SHA-256 digest, and a byte count. Execution validates the frozen
parameter mapping through `TrainingParameters`, constructs
`StageContext[TrainingParameters]`, and passes that context as the function's
sole argument. The implementation lives in [stages.py](../src/viper/stages.py).

The project can start the complete coordinator from its normal Python entrypoint:

```python
if __name__ == "__main__":
    viper.run(train)
```

```bash
python train.py --run path/to/spec.yaml --stage train --repository-root .
```

The CLI exposes the same application coordinator:

```bash
viper run path/to/spec.yaml --repository-root .
```

The Python adapter first checks that the launched callable matches the path,
symbol, bytes, decorator kind, and parameter class selected by the plan. It
then delegates complete-plan execution to `viper.api.run`. See
[api.py](../src/viper/api.py) and [api.py](../src/viper/api.py).

## 4. From experiment decisions to a frozen plan

An experiment definition declares factors, variants, replicates, and metrics.
A variant selects one permitted level for each factor and supplies the stage
parameters. A replicate supplies the run's global seed. The author then selects
the source commit, shared environment, reproducibility controls, ordered stage
specifications, and estimator artifact.

`freeze_run_plan()` validates those inputs before writing the canonical stage
and run specifications. For each project-owned Python implementation, freezing
checks the local bytes against the selected Git commit. The freeze operation
applies that check to stage callables, parameter classes, project HTTP
transports, and artifact loaders. Preflight applies the corresponding check to
each metric implementation selected by the experiment. Each `RunStageRef` then
identifies one exact stage file by path, digest, and byte count. The complete
`RunSpec` carries the ordered references once.
[authoring.py](../src/viper/authoring.py) implements freezing, and
[preflight.py](../src/viper/preflight.py) implements the host-side metric check.

The resulting dependency chain is:

```text
experiment + variant + replicate
              |
              v
source, environment, controls, and ordered stages
              |
              v
       freeze_run_plan()
              |
              v
 RunSpec + exact stage-spec files
```

Freezing establishes identity and validity. Execution supplies runtime facts.

## 5. Preflight and controlled process startup

Preflight inspects the complete frozen plan on the selected host. It verifies
the plan's Git identity, source repository, stage bytes, callables, parameter
models, metrics, artifact loaders, HTTP transports, environment requirements,
and same-run dependencies. Each check has a stable code, which lets humans and
agents respond to a specific failure. [preflight.py](../src/viper/preflight.py)
defines the check set.

The runner allocates an attempt ID under an operating-system-managed lock and
writes the allocation event before stage execution. It then applies the
run-wide startup controls before importing project code. These controls include
the global seed, named NumPy generators, PyTorch determinism settings,
floating-point policy, thread counts, DataLoader configuration, and CUDA device
selection.

Each stage runs in a child process created with the interpreter already running
VIPER. This preserves the installed environment across the parent and worker.
The child observes its host, CPU, compute backend, Python runtime, PyTorch
runtime, NumPy runtime, and native numerical libraries. It returns those facts
with a startup receipt that identifies the applied controls and initialized
generators. The process path is implemented by
[stage_execution.py](../src/viper/stage_execution.py),
[_workers/stages.py](../src/viper/_workers/stages.py), and
[runtime.py](../src/viper/runtime.py).

```text
frozen stage specification
          |
          v
validated StageContext binding
          |
          v
controlled child-process startup
          |
          v
typed live StageContext
          |
          v
project stage callable
          |
          v
outputs + invocation and runtime evidence
```

The persisted binding contains stable repository-relative values. The live
context contains runtime objects such as `Path` instances, metric handles, and
NumPy generator objects. This division lets project code receive useful Python
objects while the verifier receives a serializable description of the same
invocation.

## 6. Inputs, acquisition, and data-use roles

An internal stage consumes either a stored artifact selected before the run or
an artifact produced by an earlier stage in the same plan. Stored inputs enter
through an artifact pointer. VIPER follows the pointer to the producing run,
verifies that run, retrieves the selected artifact, and materializes it at the
path fixed by the consumer stage. Same-run inputs resolve directly to the
canonical output path of an already completed stage. The materialization logic
lives in [materialization.py](../src/viper/materialization.py).

A download stage uses a controlled HTTP request. The frozen request includes
the canonical URL, accepted response statuses, expected body digest, and
expected byte count. The selected transport retrieves the body into a bounded
workspace. VIPER verifies the body identity before the download callable can
read it through `DownloadContext.retrievals`. The built-in HTTPX transport
covers ordinary requests. A project can decorate another transport, including
one backed by an external executable, while retaining the same request,
credential, response, and body-verification contract. [http.py](../src/viper/http.py)
implements both transport forms.

Every input and artifact carries one data-use role. The roles form an ordered
restriction from training through benchmark use. During plan verification,
VIPER rejects evaluation or benchmark inputs selected by a training stage. It
also rejects an output whose role weakens the strongest restriction inherited
from the stage's inputs. The exact checks appear in
[verification.py](../src/viper/verification.py).

This rule makes leakage visible at the plan boundary. The project still assigns
the initial scientific role when a source artifact first enters the provenance
graph; VIPER verifies subsequent propagation.

## 7. Artifacts and exact training continuation

A stage declares each output before execution. A file artifact names one file.
A bundle artifact names one directory whose complete regular-file set becomes
part of the stage snapshot. Every resolved file carries a byte count and
SHA-256 digest. Project-defined loaders establish that custom representations
can be loaded. Reserved core artifacts receive additional semantic validation.

A training stage produces one terminal checkpoint. The checkpoint contains the
`parameters` artifact and the `resume_state` artifact. `ResumeState` preserves
the optimizer state, main-process generator states, and stateful DataLoader
state. Restoration loads the model parameters first, then restores the saved
optimizer, loader, and generator values before a new loader iterator is
created. [resume.py](../src/viper/resume.py) implements capture, safe loading, and
restoration.

The current resume contract supports DataLoaders with zero or multiple workers
through TorchData's stateful loader interface. The saved configuration fixes
the worker count, prefetch factor, persistent-worker setting, and ordered
delivery. A continuation attempt must recreate that configuration before
loading the saved loader state.

## 8. Metrics, evaluation, and benchmark confirmation

A metric implementation is a decorated project function or stateful class.
`MetricSpec` fixes its ID, scientific role, implementation bytes, parameters,
production mode, dependencies, and floating-point comparator when
recomputation applies. Live metrics write measurements during a stage through
runner-owned handles. Recomputed metrics run in dedicated workers from verified
dependencies and frozen parameters. The verifier compares the independently
recomputed value with the recorded measurement. [metrics.py](../src/viper/metrics.py)
and [metric_execution.py](../src/viper/metric_execution.py) implement those paths.

An evaluation measures one candidate. `EvaluateSpec` fixes the candidate model,
evaluation dataset, split inputs, metric IDs, evaluation parameters, and
prediction output. The logical artifact name is `predictions`; the project
chooses its physical representation and loader.

A benchmark applies one evaluation definition across candidates and requires
an independent confirmation. `BenchmarkSpec` repeats the evaluation identity,
dataset, splits, and metric criteria so one benchmark can govern several run
plans. After the candidate succeeds, `execute_benchmark()` runs the same frozen
plan as a new confirmation attempt. The benchmark compares the complete
`parameters` and `predictions` artifact descriptions and applies its thresholds
to independently recomputed metric values. [benchmark.py](../src/viper/benchmark.py)
constructs the result; `verify_benchmark_result()` in
[verification.py](../src/viper/verification.py) checks it.

```text
verified candidate attempt
           |
           v
new confirmation attempt from the same RunSpec
           |
           v
parameters and predictions parity
           |
           v
independently recomputed metric criteria
           |
           v
verified BenchmarkResult
```

The confirmation repeats one frozen computation. Each competing architecture
belongs to its own run plan.

## 9. Attempts, immutable publication, and verification

An attempt is one execution of a frozen plan. VIPER allocates successive
attempt IDs and keeps one durable journal of state transitions. A successful,
failed, cancelled, or preempted attempt publishes a canonical
`attempts/<attempt_id>/resolved.yaml` file. Failure evidence names the operation,
stage when applicable, time, and typed failure code. A retry appends another
attempt while preserving the same plan and all earlier evidence.

Stage results and attempt files are published in separate content-addressed
revisions beneath `.viper/store`. A stage snapshot contains the resolved stage
specification and every declared artifact file. The attempt publication
contains its journal, invocation receipts, measurements, metric-verification
files, and logs. `ResolvedRun` references each canonical attempt file by
storage location, byte count, and digest. [local_store.py](../src/viper/local_store.py),
[journal.py](../src/viper/journal.py), and [workspace.py](../src/viper/workspace.py)
implement these operations.

Terminal verification begins with `ResolvedRun`. The verifier retrieves the
frozen `RunSpec`, exact stage files, and canonical attempt documents. It checks
the plan relationships, stage order, invocation identity, requested and
observed environments, input lineage, artifact completeness, loader results,
measurements, metric recomputation, attempt transitions, and selected estimator.
Every reference is checked against its stored digest and byte count before its
contents support a later claim. [verify_run_result()](../src/viper/verification.py)
returns the connected verified plan, attempts, successful stage results, and
measurements.

## 10. Deployment model

VIPER executes inside the host selected by the user. A workstation and an
already provisioned GCE virtual machine use the same Python and CLI interfaces.
GCE provisioning remains an infrastructure operation performed before VIPER
starts. `GCEEnvironmentSpec` fixes the immutable boot or machine image, machine
type, compute request, dependency lockfile, and Python environment. The stage
worker records the observed GCE host, CPU, selected CUDA device, driver,
PyTorch CUDA runtime, and cuDNN runtime. The verifier joins those observations
to the requested environment.

The current compute contract supports one host process per stage and one
selected CUDA device. Multi-host and multi-GPU distributed execution requires
a future contract for rank topology, per-rank evidence, collective-library
configuration, and distributed checkpoint identity. The current preflight
rejects a distributed request.

The `0.1.0a1` wheel has run successfully on a pre-provisioned NVIDIA L4 GCE
instance. The live gate executed the generated acquisition, five-stage
candidate, Python entrypoint, benchmark confirmation, and terminal verification.
The [release report](releases/0.1.0a1.md) records the exact wheel digest,
machine identity, runtime versions, commands, and results.

## 11. Human and agent interfaces

The application module exposes typed request, success, and failure models for
each public operation. The CLI delegates to that module and can emit one
canonical JSON result with a stable error code. `viper schema` exposes the
registered JSON Schemas. `viper capabilities` reports the installed operations,
schemas, decorators, contexts, and execution backends. These discovery
operations let an agent inspect the accepted contract before constructing or
executing a plan.

Inspection operations work from verified documents. `status` reads an attempt
journal. `plan-diff` compares two frozen plans. `compare-runs` compares two
verified terminal runs. `lineage` returns the directed upstream graph for a
verified run. Their Python interfaces live in [inspection.py](../src/viper/inspection.py),
and their stable application surface is defined in
[api.py](../src/viper/api.py).

The machine-readable interface gives an agent bounded actions and explicit
failure identities. The provenance guarantee still depends on the frozen plan,
the controlled runner, the stored evidence, and the verifier checks described
above.

## 12. Guarantee boundary and current limitations

VIPER verifies the claims represented by its protocol. It establishes byte
identity for referenced files, validates cross-document relationships, records
the effective runtime, enforces declared data-use roles, and reconstructs the
lineage of successful outputs. Benchmark verification adds an independent
execution, artifact parity, and recomputed metric criteria.

Project-owned Python executes inside trusted local worker processes in this
release. Stage callables, custom HTTP transports, metrics, and artifact loaders
therefore require trusted source repositories. The worker boundary provides
controlled invocation and evidence capture. Trusted-source policy governs the
code admitted to that boundary. Adversarial isolation remains a future
hardening contract.

Typed stage invocation proves that the validated parameter object reached the
selected callable. Project tests remain responsible for proving how that
callable uses each field. Epoch-completion receipts and the corresponding
heightened-oversight policy remain deferred work.

The local content-addressed store supplies immutable files within one project
repository. Remote publication backends remain future work. GCE use relies on
running VIPER inside an already provisioned host. Distributed execution also
remains outside the `0.1` compute contract.

Artifact loaders prove loadability for project-defined formats. Reserved core
artifacts receive core semantic validation. A custom loader's scientific
interpretation remains part of the trusted project implementation unless the
protocol defines a corresponding semantic schema.

VIPER 0.1.0a1 is available from PyPI. The
[release report](releases/0.1.0a1.md) records the signed source tag, published
file identities, installed-package checks, and live GCE result.

## 13. Conclusion

VIPER connects an authored experiment to a verified result through one explicit
chain. The run plan fixes the intended computation. Controlled workers execute
the selected project code and record the realized environment. Immutable stage
and attempt files preserve the inputs, outputs, measurements, and failures. The
verifier reconstructs those relationships before accepting the terminal model
or benchmark result.

That chain gives humans and agents the same operating rule: change the project
through a new frozen plan, execute the plan through VIPER, and accept the result
only after verification succeeds.

## 14. Works cited

1. VIPER, [active provenance protocol](ProvenanceS1_v3.md), schema version 1.
2. VIPER, [public Python API](PUBLIC_API.md), approved `0.1` interface.
3. VIPER, [application API](APPLICATION_API.md), typed Python and CLI operations.
4. VIPER, [implementation contracts](contracts/README.md), current contract
   status and release gates.
5. VIPER, [package release candidate](releases/0.1.0a1.md), commit and executed
   acceptance evidence.
6. VIPER source, [run models](../src/viper/runs.py) and
   [stage models](../src/viper/stages.py), authored and resolved document definitions.
7. VIPER source, [plan authoring](../src/viper/authoring.py), canonical freezing and
   source-identity checks.
8. VIPER source, [stage interface](../src/viper/stages.py) and
   [stage execution](../src/viper/stage_execution.py), typed invocation and worker
   launch.
9. VIPER source, [project initialization](../src/viper/project_init.py), generated
   user-project source and tests.
10. VIPER source, [complete-plan execution](../src/viper/execution.py) and
   [verification](../src/viper/verification.py), attempt execution, publication, and
   verification.
11. VIPER tests, [generated-project acceptance](../tests/test_generated_project_acceptance.py),
    installed-project acquisition, five-stage execution, benchmark, and
    verification path.
