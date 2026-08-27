# VIPER

VIPER defines and verifies reproducible machine-learning experiments. Before a
run, it fixes the dataset, source commit, stage specifications, environment,
and reproducibility controls. After the run, it checks the recorded inputs,
outputs, measurements, and trained model against that plan.

Install the `viper-provenance` distribution. Its Python package and command are
both named `viper`.

## Directory map

| File or directory | Role | Principal interface |
|---|---|---|
| [project briefing](docs/PROJECT_BRIEFING.md) | States the verified deployment position and immediate publication gate | Release evidence and next owner action |
| [technical overview](docs/VIPER_TECHNICAL_OVERVIEW.md) | Explains VIPER from frozen plan through execution, evidence, verification, and deployment | Complete system mechanism and guarantee boundary |
| [v3 protocol](docs/ProvenanceS1_v3.md) | Defines the active formal and protocol contract | Sections 1–23 |
| [application API](docs/APPLICATION_API.md) | Defines the typed Python, CLI, and agent-facing operation contract | Operations, parameters, results, errors, and discovery |
| [public Python API](docs/PUBLIC_API.md) | Defines supported imports, extension points, compatibility, and repository validation | Public modules, stage interface, test tiers, and release boundary |
| [development guide](docs/DEVELOPMENT.md) | Defines the repository environment and validation commands | Fast, integration, release, live-CUDA, and domain gates |
| [getting started](docs/GETTING_STARTED.md) | Shows the installed project, stage, run, retry, benchmark, and GCE path | `viper init`, decorators, Python execution, and CLI execution |
| [implementation contracts](docs/contracts/README.md) | Defines each release claim from declaration through acceptance | Parameter delivery, HTTP retrieval, metrics, artifacts, attempts, benchmarks, cloud execution, and packaging |
| [publication checklist](docs/PUBLICATION_TODO.md) | Tracks implementation and release work | Protocol, runner, package, and distribution tasks |
| [versioning policy](docs/VERSIONING.md) | Separates software releases from serialized document schemas | Semantic package versions and document `schema_version` values |
| [run contracts](src/viper/runs.py) | Defines frozen run plans, durable attempts, and terminal run outcomes | `RunSpec`, `RunAttempt`, `ResolvedRun` |
| [verification](src/viper/verification.py) | Retrieves referenced files and checks cross-record relationships | `verify_run_result()`, `verify_benchmark_result()` |
| [training resume](src/viper/resume.py) | Captures, serializes, restores, and validates optimizer, generator, and stateful-loader state | `capture_resume_state()`, `restore_resume_state()` |
| [plan authoring](viper/authoring.py) | Writes canonical experiment, variant, benchmark, stage, and frozen run-plan files | `freeze_run_plan()`, `write_experiment_spec()`, `write_variant_spec()` |
| [stage execution](src/viper/stage_execution.py) | Invokes one canonical stage command and hashes every declared output file | `execute_stage_process()` |
| [current runner](viper/runner.py) | Executes and verifies a complete frozen run in the implemented trusted-host environment | `run()` |
| [preflight](viper/preflight.py) | Checks the committed plan, source repository, environment kind, stage identities, code paths, plan relationships, and metric implementations | `preflight_local_plan()` |
| [local storage](viper/local_store.py) | Publishes immutable stage snapshots and run files beneath `.viper/store` | `LocalArtifactStore` |
| [installed command](viper/cli.py) | Exposes authoring, preflight, execution, validation, verification, and discovery | `viper preflight`, `viper run`, `viper verify-run` |
| [serialization](src/viper/serialization.py) | Encodes protocol documents and parses duplicate-key-safe YAML | `serialize_document()`, `parse_yaml_bytes()`, `load_stage_spec()`, `load_resolved_stage()` |
| [examples](examples/) | Supplies a user-project extension tree and loadable protocol records | Project code plus download and build records |
| [identifiers](viper/ids.py) | Defines run and human-readable identifier types | `RunId`, `HumanId` |
| [inspection](viper/inspection.py) | Reads durable attempt state and compares frozen plans, verified runs, and lineage through stable machine-readable paths | `attempt_status()`, `plan_diff()`, `compare_runs()`, `lineage()` |
| [metrics](viper/metrics.py) | Defines project metric decorators, stateful metrics, comparison, and measurement output | `metric()`, `StatefulMetric`, `MeasurementSink` |
| [parameters](viper/parameters.py) | Defines the public parameter categories that projects specialize | `Download`, `Build`, `Embed`, `Train`, `Evaluate`, `Metric`, `HttpTransport` |
| [worker](viper/worker.py) | Executes one project command through an execution backend | `WorkerRequest`, `execute_worker()` |
| [workspace](viper/workspace.py) | Creates bounded attempt directories and exclusive run ownership | `AttemptWorkspace` |
| [journal](viper/journal.py) | Persists synchronized attempt transitions | `DurableJournal` |
| [package exports](viper/__init__.py) | Exposes the supported authoring, execution, identifier, protocol, and resume modules | Public package imports |
| [supporting documents](docs/) | Contains the active protocol, implementation contracts, publication checklist, and supporting explanations | Markdown documents and figures |
| [archive](archive/) | Retains prior model drafts and protocol documents | Reference material |
| [v1 protocol](archive/ProvenanceS1.md)<br>[v2 protocol](archive/ProvenanceS1_v2.md) | Retains earlier protocol specifications | Reference material |

The focused model, verifier, and acceptance checks live in the
[repository test directory](tests/).

## Protocol and verification flow

The [run contracts](src/viper/runs.py) and [stage contracts](src/viper/stages.py)
divide requested state from realized state. A `RunSpec` and its ordered stage
specs form the frozen run plan. Each completed
stage publishes one `ResolvedStageRef` containing a resolved stage spec and all
declared artifact files at one immutable snapshot.

```text
RunSpec + ordered stage specs
              │
              ▼
    permitted runtime-state set
              │
              ▼
RunAttempt.resolved_stages[]
              │
              ▼
ResolvedStageRef.snapshot
├── resolved stage spec
└── exact files for every named artifact
              │
              ▼
          ResolvedRun
              │
              ▼
      verify_run_result()
```

The [verification module](src/viper/verification.py) starts from `ResolvedRun.spec`, verifies the exact
RunSpec bytes, loads experiment and variant records, retrieves every stage
spec, and checks the realized environment, command, inputs, artifacts,
measurements, logs, and terminal estimator. Artifact loaders are selected by
`ArtifactSpec.loader` from the exact Git commit recorded by `RunSpec.source`.

`verify_benchmark_result()` verifies a second successful attempt, its complete
input lineage, estimator and prediction file parity, metric criteria, and
result status. `verify_promoted_artifact()` verifies the selected producer run
and any benchmark result required to authorize estimator promotion.

An evaluation measures one candidate. A benchmark standardizes that evaluation
across candidates and requires a reproducible, threshold-qualified result.
`EvaluateSpec` binds the candidate parameters, evaluation inputs, metrics,
execution parameters, and outputs. `BenchmarkSpec` repeats the evaluation ID,
dataset, splits, and metric IDs, then adds metric thresholds and a fixed
execution count. The verifier requires the repeated values to match, which
allows one benchmark to govern multiple candidate run plans.

Every stored input and produced artifact declares a data-use role: `training`,
`validation`, `evaluation`, or `benchmark`. The verifier confirms stored-input
roles against their producer artifacts, propagates same-run roles, prevents a
stage from weakening an inherited restriction, and blocks evaluation or
benchmark data from entering a training stage.

## Public operations

- `load_stage_spec(path)` parses a `DownloadSpec`, `BuildSpec`, `EmbedSpec`,
  `TrainSpec`, or `EvaluateSpec` through the discriminated `Spec` union.
- `load_resolved_stage(path)` parses the corresponding realized record through
  `ResolvedSpec`.
- `verify_run_result(resolved_run, policy=..., fetcher=...)` verifies one
  terminal run and returns its connected run plan, successful resolved stages,
  and measurements.
- `verify_benchmark_result(result, policy=..., fetcher=...)` verifies the benchmark record,
  selected run, confirmation attempt, parity, and metric thresholds.
- `verify_promoted_artifact(pointer, policy=..., fetcher=...)` verifies a promoted
  artifact's producer lineage and benchmark authorization when required.
- `capture_resume_state(...)` captures optimizer state, main-process
  generator state, and the stateful DataLoader state at a training-stage
  boundary.
- `restore_resume_state(...)` restores those values before the next
  DataLoader iterator is created.
- `save_resume_state(path, resume_state)` and
  `load_resume_state(path)` write and safely load the reserved
  `resume_state` artifact.
- A custom `fetcher` receives a `GitFileRef` or `HuggingFaceFileRef` and returns
  bytes. Omitting it uses the package Git and Hugging Face retrieval functions.
- `VerificationPolicy` lists the exact source repositories whose artifact
  loader code may execute. Verification fails before loader retrieval when the
  run source is absent from that list.
- `freeze_run_plan(repository_root, draft)` validates and canonicalizes each
  stage spec, records its exact hash and byte count, and writes the sibling
  stage and run `spec.yaml` files.
- `execute_stage_process(...)` verifies the frozen stage-spec bytes, invokes
  the canonical command, and records every produced artifact file.
- `preflight_plan(repository_root, run_spec_path)` checks the complete plan on
  the active host and returns every applicable named check.
- `run(repository_root, run_spec_path)` executes every stage, publishes
  immutable stage results, writes the terminal `resolved.yaml`, and verifies
  the completed run.
- `plan_diff(...)` verifies and compares two RunSpecs and every stage spec they
  identify.
- `lineage(...)` verifies one terminal run and returns its directed upstream
  provenance graph.

## Current local execution

Freeze the plan, inspect it, then execute it from the project repository:

```bash
viper freeze-run <draft.yaml>
viper preflight <run-spec-path>
viper run <run-spec-path>
```

`RunSpec.source.commit` identifies the project source, environment lockfile,
metric implementations, and artifact loaders. The Git revision containing the
run spec identifies the frozen plan files. VIPER checks both revisions before
execution.

The local runner creates an exclusive attempt workspace, applies the run-wide
reproducibility controls, invokes each stage through the VIPER runtime
bootstrap, materializes declared inputs, publishes immutable results, and runs
the complete verifier before returning success.

## Python execution interface

Project code declares stage callables with VIPER decorators and executes them
through ordinary Python:

```python
import viper


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    ...


if __name__ == "__main__":
    viper.run(train)
```

```bash
python train.py --run <run-spec> --stage train
```

The installed `viper run <run-spec>` command will execute a complete plan
through the same application coordinator. Local and GCE execution use the same
interfaces. The user invokes VIPER inside the selected host; VIPER records and
verifies that host's realized environment.

The approved mechanics live in the [stage-invocation](docs/contracts/STAGE_INVOCATION.md),
[process-startup](docs/contracts/PROCESS_STARTUP.md), and
[cloud-execution](docs/contracts/CLOUD_EXECUTION.md) contracts.

## Validation

Run the fast development gate from the repository root after activating the
`mantra` Conda environment described in the
[development guide](docs/DEVELOPMENT.md):

```bash
make check
```

The command runs Ruff, formatting, Pyright, and the unit and contract tests. The
integration gate exercises process, runner, CLI, resume, and durable-attempt
boundaries. The release gate adds the complete generated-project acceptance
case:

```bash
make check-integration
make check-release
```

Pytest still honors direct file selection. For example,
`python -m pytest tests/test_runner_acceptance.py -q` runs that complete module.

## Current boundaries

- `LocalEnvironmentSpec` and `GCEEnvironmentSpec` use the same in-place runner.
  GCE execution records the immutable provisioning image, machine type, CPU,
  CUDA backend, lockfile, and Python environment.
- Every internal stage binds its versioned JSON parameters to an exact
  project-owned Pydantic class. VIPER validates the class and values during
  plan freezing, preflight, and execution.
- Evaluation reserves the logical artifact name `predictions`. The project
  selects its file or bundle format and declares the exact loader path.
- Data-use roles are assigned by the project when source artifacts enter the
  provenance graph. VIPER verifies their propagation and permitted stage
  flows. The project assigns the scientific role when the artifact enters the
  graph.
- Each experiment metric records its role, parameters, and exact
  repository-relative implementation path.
- VIPER accepts any user source-tree layout. Stage scripts, metric
  implementations, and artifact loaders are selected by exact
  repository-relative paths and fixed by `RunSpec.source`.
- Artifact loaders execute Python from the Git commit named by `RunSpec.source`.
  Verification therefore accepts only run sources trusted to execute in the
  verifier process.
- The runner publishes successful, failed, cancelled, and preempted attempts,
  preserves completed-stage evidence, and retries the same frozen plan through
  `viper.run(stage_callable)`, `viper run`, or `viper retry`.
