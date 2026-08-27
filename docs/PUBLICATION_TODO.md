# VIPER master execution checklist

This file is the single implementation and publication checklist for
VIPER. Phases 0–10 record the completed `0.1.0a1` release. Phases 11–21 govern
the `0.1.0a2` public-repository revision. The
[protocol](ProvenanceS1_v3.md) owns serialized provenance semantics. The
[application API](APPLICATION_API.md) owns public operations. The
[contract index](contracts/README.md) owns the mechanics required to support
each release claim.

## Contents

1. [Release boundary](#release-boundary)
2. [Checklist rules](#checklist-rules)
3. [Contract coverage](#contract-coverage)
4. [Implemented baseline](#implemented-baseline)
5. [Phase 0: specification audit](#phase-0-audit-the-contract-stack)
6. [Phase 1: stage invocation and process startup](#phase-1-implement-stage-invocation-and-process-startup)
7. [Phase 2: controlled HTTP retrieval](#phase-2-implement-controlled-http-retrieval)
8. [Phase 3: artifact validation](#phase-3-close-artifact-validation)
9. [Phase 4: metric provenance](#phase-4-close-metric-provenance)
10. [Phase 5: durable attempts and retry](#phase-5-implement-durable-attempts-and-retry)
11. [Phase 6: benchmark execution](#phase-6-implement-benchmark-execution)
12. [Phase 7: local and GCE execution](#phase-7-generalize-execution-across-local-and-gce-hosts)
13. [Phase 8: public interface and project scaffold](#phase-8-freeze-the-public-interface-and-project-scaffold)
14. [Phase 9: release candidate](#phase-9-build-and-validate-the-release-candidate)
15. [Phase 10: publication](#phase-10-publish-viper-010a1)
16. [Phase 11: publication procedure](#phase-11-author-the-publication-procedure)
17. [Phase 12: module ownership](#phase-12-freeze-module-ownership)
18. [Phase 13: public repository](#phase-13-create-the-public-repository)
19. [Phase 14: protocol decomposition](#phase-14-decompose-the-protocol)
20. [Phase 15: execution and verification](#phase-15-decompose-execution-and-verification)
21. [Phase 16: application consolidation](#phase-16-consolidate-the-application-surface)
22. [Phase 17: runnable example](#phase-17-replace-the-example-suite)
23. [Phase 18: public documentation](#phase-18-rewrite-the-public-documentation)
24. [Phase 19: release candidate](#phase-19-build-and-validate-010a2)
25. [Phase 20: live GCE acceptance](#phase-20-run-live-gce-acceptance)
26. [Phase 21: publication](#phase-21-publish-viper-010a2)
27. [Deferred work](#deferred-work)

## Release boundary

VIPER 0.1 is ready when an installed wheel can execute and verify one complete
project on a trusted local machine and a trusted, pre-provisioned GCE instance.
The project may start through its ordinary decorated Python module or the
generic `viper run` command. Both interfaces submit the same frozen plan to one
application coordinator.

The release must complete this path:

```text
author project extensions
-> freeze plan
-> preflight plan
-> execute ordered stages
-> publish stage and attempt evidence
-> verify terminal run
-> execute benchmark confirmation
-> verify benchmark result
```

The alpha release trusts the project source named by `RunSpec.source` and the
single host on which VIPER runs. The user's infrastructure tooling owns VM
provisioning, terminal access, source placement, and cloud-resource lifecycle.

Five owner inputs enter at fixed points:

| Owner input | Required by |
|---|---|
| Package license | Phase 9 metadata gate |
| Author names and contact metadata | Phase 9 metadata gate |
| TestPyPI trusted-publisher registration | Phase 10 TestPyPI upload |
| PyPI environment approval | Phase 10 PyPI upload |
| Release-tag signing identity and configuration | Phase 10 signed tag |

## Checklist rules

A checkbox closes after its code, tests, examples, and public documentation
agree. Complete each phase in document order.

Every implementation phase ends with this repository gate:

```bash
ruff check src/viper tests examples/project/src
pyright --pythonpath "$(command -v python)"
python -m pytest -q
git diff --check
```

Each listed commit boundary receives a focused commit and a successful push.
The local branch and `origin/main` must identify the same commit before the next
phase begins.

When implementation reveals an incomplete contract, revise the owning file in
`docs/contracts/`, review that revision, and resume implementation from the
approved text.

Each phase also updates the affected sections of `ProvenanceS1_v3.md`. A phase
closes when its implementation contract, formal protocol, public API,
implementation, and tests describe the same fields and guarantees.

Items marked **Owner input** require a licensing, identity, credential, or
publication decision from the package owner.

## Contract coverage

Every implementation contract appears once in the execution sequence.

| Contract | Current status | Execution phase | Completion evidence |
|---|---|---|---|
| [Parameters](contracts/PARAMETERS.md) | Implemented | Regression coverage in Phases 1 and 2 | The exact project class validates the frozen parameter mapping. Phase 1 owns typed delivery. |
| [Stage invocation](contracts/STAGE_INVOCATION.md) | Implemented | Phase 1 | The frozen callable receives typed parameters and declared paths. Python and CLI execution share one verified coordinator path. |
| [Process startup](contracts/PROCESS_STARTUP.md) | Implemented | Phase 1 | The controlled child records its startup environment, applied controls, initialized generators, delivered generators, and observed runtime. The designated L4 acceptance gate passed for CPU and CUDA stages. |
| [HTTP retrieval](contracts/HTTP_RETRIEVAL.md) | Implemented | Phase 2 | Each declared input binds its frozen request, expected body identity, selected transport, terminal response, external executable identity, and delivered context handle. HTTPX and project transports pass one conformance suite. |
| [Artifact validation](contracts/ARTIFACT_VALIDATION.md) | Implemented | Phase 3 | The verifier reports representation identity, loadability, or reserved semantic validity at its established level. |
| [Metric provenance](contracts/METRIC_PROVENANCE.md) | Implemented | Phase 4 | Recomputed metrics bind exact dependencies and two run-owned worker executions; live metrics bind a controlled metric handle and measurement sink. |
| [Attempt execution](contracts/ATTEMPT_EXECUTION.md) | Implemented | Phase 5 | VIPER publishes canonical attempt documents, references them immutably, retries the same frozen plan, and closes real cancellation and preemption signals with active-stage evidence. |
| [Benchmark execution](contracts/BENCHMARK_EXECUTION.md) | Implemented | Phase 6 | `execute_benchmark()` produces one independent confirmation and persists the artifact and metric comparison receipts accepted by `verify_benchmark()`. |
| [Cloud execution](contracts/CLOUD_EXECUTION.md) | Implemented | Phase 7 | The installed wheel executes in place on GCE and verifies the host, backend, and exact Python environment. |
| [Package release](contracts/PACKAGE_RELEASE.md) | Approved | Phases 11–21 | The clean public repository, installed distributions, generated example, and registry files pass the release gate. |

## Implemented baseline

The current repository supplies the foundation consumed by Phase 1:

- [x] Pydantic models for authored stages, resolved stages, run attempts,
  terminal runs, evaluations, artifact pointers, and benchmark results.
- [x] Canonical YAML parsing and run-plan freezing.
- [x] Project-defined parameter classes with source identity and strict value
  validation.
- [x] Training, validation, evaluation, and benchmark data-role enforcement.
- [x] Resume-state capture and restoration for zero-worker and multiprocess
  `StatefulDataLoader` execution.
- [x] Successful trusted-local execution of an ordered two-stage plan.
- [x] Verified input materialization, immutable local snapshots, measurements,
  logs, terminal `resolved.yaml`, and terminal run verification.
- [x] Metric decorators, measurement writing, floating-point comparators, and
  post-stage recomputation.
- [x] Benchmark verification from supplied candidate and confirmation
  evidence.
- [x] Typed application operations, JSON dispatch, CLI parsing, schema
  discovery, capability discovery, plan comparison, run comparison, lineage,
  and attempt status.
- [x] Build configuration, a four-version CI matrix, and installed-wheel import
  smoke commands.
- [x] Ruff, Pyright, 161 tests, and 15 subtests at implementation baseline
  `68cfe01`.
- [x] Contract audit, Ruff, Pyright, 186 tests, and 15 subtests after the
  attempt, startup, interface-parity, and HTTP conformance increments.

### Named verifier-rule coverage

Each implementation phase must add the rules owned by its contract and the
rejection tests named there.

| Contract | Verifier rules |
|---|---|
| Artifact validation | `artifact.representation`, `artifact.bundle`, `artifact.loader`, `artifact.loadability`, `artifact.semantic.resume_state` |
| Attempt execution | `attempt.order`, `attempt.terminal`, `attempt.identity`, `attempt.files`, `attempt.failure`, `attempt.invocations`, `attempt.retry`, `attempt.purpose` |
| Benchmark execution | `benchmark.plan`, `benchmark.confirmation`, `benchmark.artifacts`, `benchmark.metrics`, `benchmark.status` |
| Cloud execution | `environment.kind`, `gce.provisioning`, `gce.machine_type`, `gce.compute`, `gce.lockfile`, `gce.python`, `runtime.controls`, `run.result` |
| HTTP retrieval | `http.input`, `http.request`, `http.policy`, `http.credentials`, `http.transport.identity`, `http.transport.parameters`, `http.transport.executable`, `http.response`, `http.content`, `http.delivery`, `parameter_model.identity`, `parameter_model.validation`, `stage.source`, `artifact.files` |
| Metric provenance | `metric.implementation`, `metric.dependencies`, `metric.parameters`, `metric.measurement`, `metric.production`, `metric.environment`, `metric.recompute`, `metric.live_execution` |
| Process startup | `startup.plan`, `startup.environment`, `startup.controls`, `startup.randomness`, `startup.callable`, `startup.context`, `startup.runtime`, `startup.backend`, `startup.distributed`, `startup.outcome` |
| Stage invocation | `stage.implementation`, `stage.decorator`, `parameter_model.identity`, `parameter.value`, `stage.context`, `stage.outcome` |

## Phase 0. Audit the contract stack

**Scope:** all ten files in `docs/contracts/`, the formal protocol, the public
API specifications, the master checklist, implementation modules, verifier
rules, and declared acceptance tests.

- [x] Parse every Python model shown in a contract.
- [x] Compare repeated contract and protocol classes field by field.
- [x] Construct every implemented Pydantic protocol schema.
- [x] Trace each claim-bearing value from its producer to verifier
  reconstruction.
- [x] Map each release requirement to its protocol field, runtime operation,
  persisted evidence, verifier rule, and acceptance test.
- [x] Write one minimal counterexample for each contract's required claim and
  name the rejecting check.
- [x] Compare the contract, protocol, public API, checklist, implementation,
  and tests; record every design-state discrepancy.
- [x] Record the results and approval decision in
  `docs/contracts/AUDIT.md`.
- [x] Run `python tests/contract_audit.py` and its focused tests.

**Focused gate**

```bash
python tests/contract_audit.py
python -m pytest tests/test_contract_audit.py -q
```

**Commit boundaries**

1. `Consolidate approved VIPER contracts`
2. `Add deterministic contract auditing`
3. `Record the full contract-system audit`

## Phase 1. Implement stage invocation and process startup

**Contracts:** [Stage invocation](contracts/STAGE_INVOCATION.md) and
[Process startup](contracts/PROCESS_STARTUP.md).

### Protocol and authoring

- [x] Add `StageImplementationRef` with repository-relative path, top-level
  symbol, SHA-256, and byte count.
- [x] Replace each parameterized stage's `script` field with
  `implementation: StageImplementationRef`.
- [x] Add `StageContextBinding`, its canonical digest rule, and
  `StageInvocationReceipt` to attempt evidence.
- [x] Add `ResolvedStageInvocationRef`; store each successful stage's reference
  on its resolved stage and every started invocation on `RunAttempt`.
- [x] Add `ProcessStartupReceipt` with the allowlisted child environment,
  applied controls, and one initialized-state digest for each configured
  generator.
- [x] Update `ProvenanceS1_v3.md` with the callable, context, receipt, and
  process-startup relationships.
- [x] Add one public decorator for each stage kind.
- [x] Resolve decorator metadata into the frozen implementation and parameter
  model references.

### Runtime

- [x] Add generic `StageContext` with typed parameters, materialized input
  paths, writable artifact paths, a metric-handle mapping, run ID, attempt ID,
  and stage ID. Phase 1 supplies an empty mapping; Phase 4 binds the handles.
- [x] Return every configured named NumPy generator from child initialization
  and expose it through `StageContext.numpy_generators`.
- [x] Store the sorted generator names in `StageContextBinding` and verify them
  against `RunSpec.reproducibility` and `ProcessStartupReceipt`.
- [x] Construct the versioned logical `StageContextBinding` before resolving
  attempt-local absolute paths.
- [x] Add `viper.run(stage_callable)` as the ordinary Python adapter.
- [x] Bind `--stage` to the callable launched by the project module and execute
  every stage in `RunSpec.stages` order.
- [x] Rename `run_local()` and its request/result models to the host-neutral
  `run()` operation.
- [x] Rename `viper run-local` to `viper run`.
- [x] Derive the canonical child-process environment from
  `RunSpec.reproducibility` and the stage's effective environment.
- [x] Permit `CPUComputeSpec` and single-device `CUDAComputeSpec` on local
  environments; reject `CUDAComputeSpec.count > 1` with
  `startup.distributed`.
- [x] Launch each stage in one controlled child carrying
  `VIPER_CONTEXT_PATH`.
- [x] Apply library controls before importing the frozen callable.
- [x] Select the CPU or CUDA backend from the effective compute request and
  expose one matching CUDA device to a CUDA child process.
- [x] Observe the host `CPUContext` and the selected
  `ComputeBackendContext` inside the child process.
- [x] Validate parameters into the exact project class and place that object in
  `StageContext.params`.
- [x] Construct `StageContext.inputs` from the stage's declared,
  role-permitted inputs.
- [x] Invoke the frozen callable once and persist its invocation receipt at the
  attempt-level canonical path.

### Verification and acceptance

- [x] Verify implementation identity, decorator metadata, parameter identity,
  parameter digest, canonical context binding, startup environment, applied
  controls, initialized-generator receipts, and invocation outcome.
- [x] Replace constant fixture scripts with decorated functions that consume
  their typed parameters and declared paths.
- [x] Prove that `python train.py --run RUN --stage train` and `viper run RUN`
  produce terminal results accepted by the same verifier.
- [x] Prove that a CPU stage on a GPU-capable host records
  `CPUBackendContext`, while a one-L4 CUDA stage records the matching
  `CUDABackendContext`.
- [x] Reject a changed callable, parameter mapping, context binding, and second
  invocation.
- [x] Reject unavailable CUDA, a changed device model, and a CUDA device count
  greater than `1` through their named startup checks.

**Focused gate**

```bash
python -m pytest tests/test_stage_invocation.py tests/test_process_startup.py \
  tests/test_runner_signals.py tests/test_runner_acceptance.py \
  tests/test_api.py tests/test_cli.py -q
```

**Commit boundaries**

1. `Define frozen stage callables and typed contexts`
2. `Apply run controls through the stage child process`
3. `Route Python and CLI execution through one coordinator`

## Phase 2. Implement controlled HTTP retrieval

**Contract:** [HTTP retrieval](contracts/HTTP_RETRIEVAL.md).

### Protocol and authoring

- [x] Add `HttpRequestSpec`, `EnvironmentSecretRef`, and
  `HttpRetrievalPolicy`.
- [x] Require an expected SHA-256 and byte count for every experimental HTTP
  request.
- [x] Add `HttpOrigin`; scope each credential reference to one or more
  authorized origins.
- [x] Replace `RemoteFileRef` inputs on `DownloadSpec` with frozen HTTP request
  specifications.
- [x] Add the built-in and project `HttpTransportSpec` variants and require one
  selected transport on each `DownloadSpec`.
- [x] Add `HttpTransportImplementationRef`, `viper.parameters.HttpTransport`, and the
  `http_transport()` decorator.
- [x] Add frozen external executable requirements to each project transport.
- [x] Resolve decorated project transports to an exact callable, parameter
  class, and frozen parameter mapping.
- [x] Store one resolved retrieval per declared input on
  `ResolvedDownloadSpec`.
- [x] Bind each retrieval to its input name, frozen request, terminal response,
  selected transport, and completed body.
- [x] Add `ResolvedHttpTransport` and `ResolvedExternalExecutable` so a project
  adapter identifies its Python wrapper and every external transfer binary.
- [x] Expand URL templates during authoring and freeze the canonical request.
- [x] Reject literal authorization values and preserve secret references.

### Runtime

- [x] Add HTTPX as the built-in transport and pin it through the package and
  effective Python-environment contracts.
- [x] Construct `HttpTransportContext` and invoke either the built-in transport
  or the exact decorated project transport selected by the stage.
- [x] Enforce scheme, host, port, accepted-status, redirect-count, body-size,
  and timeout limits through
  `HttpRetrievalPolicy`.
- [x] Resolve credentials at execution time through `EnvironmentSecretRef`.
- [x] Inject each secret into its declared HTTP header and redact its value
  from requests, receipts, logs, errors, and JSON results.
- [x] Strip a credential on a cross-origin redirect unless the destination
  appears in its frozen authorized-origin set.
- [x] Assign each transport a dedicated retrieval workspace and exact body
  destination; reject returned path escape and symlinks.
- [x] Hash and store each completed body before project download code runs.
- [x] Resolve and verify every frozen external executable before transport
  invocation; supply only verified executable paths to the transport context.
- [x] Require every successful transport to return its terminal HTTP response.
- [x] Verify the expected body identity before project download code runs.
- [x] Add `DownloadContext` as the `StageContext` extension that exposes typed
  `viper.parameters.Download` and one verified retrieval handle per input.
- [x] Treat redirects and segmented range requests as internal operations of
  one transport invocation.
- [x] Keep dynamic pagination and scraping in discovery processes that publish
  immutable inputs for later experimental plans.
- [x] Deliver only verified retrieval handles through the download context.
- [x] State the 0.1 trusted-project-source boundary in public documentation;
  complete network confinement remains deferred.

### Verification and acceptance

- [x] Verify every frozen request, credential origin, selected transport,
  transport parameters, preflight executable identity, terminal response,
  expected body identity, resolved body identity, stage implementation, and
  published artifact.
- [x] Add one reusable transport conformance suite for the built-in HTTPX
  transport and decorated project transports.
- [x] Require each transport to reject an unaccepted terminal HTTP status.
- [x] Exercise one static request, redirect, range-capable source, secret
  reference, unauthorized credential origin, request-policy failure, returned
  path escape, missing executable, modified transport source, and same-length
  body tampering.
- [x] Prove that the acceptance download callable consumes the response selected
  by its frozen request.

**Focused gate**

```bash
python -m pytest tests/test_http_retrieval.py tests/test_stage_invocation.py \
  tests/test_runner_acceptance.py tests/test_verifier.py -q
```

**Commit boundaries**

1. `Define selectable HTTP transports and logical retrievals`
2. `Add decorated project HTTP transports`
3. `Execute retrievals through the selected transport`
4. `Verify HTTP retrieval provenance`

## Phase 3. Close artifact validation

**Contract:** [Artifact validation](contracts/ARTIFACT_VALIDATION.md).

- [x] Add `ArtifactLoaderRef` with path, symbol, SHA-256, and byte count.
- [x] Replace artifact loader IDs and paths with exact implementation
  references.
- [x] Rename the verifier policy field to `trusted_source_repositories` and the
  CLI option to `--trust-source`; apply it to every project code path executed
  during verification.
- [x] Enumerate every regular bundle member during publication and reject
  symlinks, path escape, missing members, and unrecorded members.
- [x] Invoke project loaders through a dedicated trusted-local worker boundary.
- [x] Report generic loader success as `artifact.loadability`.
- [x] Apply core semantic validation to the reserved `resume_state` artifact.
- [x] Update verifier errors and protocol prose to distinguish representation
  identity, loadability, and reserved semantic validity.
- [x] Exercise single-file loading, bundle loading, missing and extra members,
  same-length tampering, loader tampering, loader failure, and invalid
  `resume_state`.
- [x] Run the maintained interruption-and-resumption case with zero and two
  DataLoader workers and compare
  its resumed terminal state with the uninterrupted execution.

**Focused gate**

```bash
python -m pytest tests/test_artifact_loaders.py tests/test_artifact_validation.py \
  tests/test_verifier.py tests/test_verifier_acceptance.py -q
```

**Commit boundaries**

1. `Bind artifacts to exact loader implementations`
2. `Verify artifact representation and loadability`
3. `Validate reserved artifact semantics`

## Phase 4. Close metric provenance

**Contract:** [Metric provenance](contracts/METRIC_PROVENANCE.md).

### Protocol and authoring

- [x] Add `MetricImplementationRef`, `MetricDependency`,
  `ResolvedMetricDependency`, `MetricMode`, `MetricExecutionReceipt`, and
  `MetricVerificationReceipt`.
- [x] Add run ID and attempt ID to `MetricExecutionReceipt`; require both
  worker receipts to select the measurement's run and attempt.
- [x] Use one `MetricSpec`; its `mode` selects `recompute` or `live` execution.
- [x] Require one comparator for every recomputed floating-point metric.
- [x] Freeze decorator metadata, dependencies, parameters, and implementation
  identity into `MetricSpec`.
- [x] Require benchmark criteria to select evaluation metrics with
  `mode="recompute"`.

### Runtime and verification

- [x] Construct each recomputed `MetricContext` from its declared file
  dependencies.
- [x] Inject live metric handles into `StageContext` and bind their
  output to the active `MeasurementSink`.
- [x] Implement `MetricHandle.update()` and `record()` for function
  and stateful metric implementations.
- [x] Enforce every dependency's data role before invoking metric code.
- [x] Record live measurements through the runner-owned
  `MeasurementSink`.
- [x] Invoke recomputed metrics through a dedicated controlled worker for
  measurement production.
- [x] Launch a second dedicated worker for independent recomputation.
- [x] Persist both `MetricExecutionReceipt` values in one
  `MetricVerificationReceipt`.
- [x] Verify implementation identity, dependency identity, parameters,
  startup evidence, runtime context, measurement ownership, and comparator
  outcome.
- [x] Exercise stateless evaluation, stateful training, diagnostic,
  recomputation, tolerance, undeclared dependency, ordering, and tampering
  cases.

**Focused gate**

```bash
python -m pytest tests/test_metric_interface.py tests/test_metric_provenance.py \
  tests/test_runner_acceptance.py tests/test_verifier.py -q
```

**Commit boundaries**

1. `Bind metrics to exact implementations and dependencies`
2. `Restrict metric contexts to declared values`
3. `Persist and verify recomputed metric evidence`

## Phase 5. Implement durable attempts and retry

**Contract:** [Attempt execution](contracts/ATTEMPT_EXECUTION.md).

- [x] Replace the stale-file lock with an operating-system-managed advisory
  lock scoped to one run.
- [x] Allocate `max(persisted attempt IDs) + 1` while holding that lock.
- [x] Write the allocation event before preflight begins.
- [x] Persist every attempt transition before its associated side effect.
- [x] Write one standard-output file and one standard-error file for each stage
  invocation.
- [x] Preserve every verified stage snapshot completed before an attempt ends.
- [x] Persist one `StageInvocationReceipt` for every started stage and include
  its `ResolvedStageInvocationRef` in `RunAttempt.invocations`.
- [x] Close and publish successful and failed attempts with their terminal
  status and typed evidence.
- [x] Map `SIGINT` to `cancelled` and `SIGTERM` to `preempted`; close each
  observed interruption through the terminal-attempt path.
- [x] Replace `failure_reason` with typed `AttemptFailure`.
- [x] Publish every attempt as `attempts/<attempt_id>/resolved.yaml`; place its
  journal, invocations, measurements, metric-verification receipts, and logs
  beneath the same attempt directory.
- [x] Add `ResolvedAttemptRef`; replace `ResolvedRun.attempts: tuple[RunAttempt,
  ...]` with ordered references to the canonical attempt documents and verify
  each referenced document's path, byte count, SHA-256, and attempt ID.
- [x] Add `AttemptJournalRef` and metric-verification files to `RunAttempt`.
- [x] Add attempt purpose; keep ordinary attempts in `ResolvedRun` and bind the
  independent confirmation directly to `BenchmarkResult`.
- [x] Reconcile an abandoned nonterminal journal as `coordinator_lost` after
  acquiring its released lock.
- [x] Add `retry()` and `viper retry`; each retry uses the same frozen plan and
  the next attempt ID.
- [x] Verify attempt ordering, terminal status, failure identity, attempt files,
  and retry plan identity.
- [x] Exercise an abandoned attempt, a failed attempt, a successful retry, and
  tampered prior evidence in the complete two-stage acceptance case.
- [x] Exercise `SIGINT` cancellation and `SIGTERM` preemption through real
  coordinator processes; verify each terminal status, typed failure, journal,
  logs, and preserved completed-stage prefix.

**Focused gate**

```bash
python -m pytest tests/test_worker.py tests/test_runner_acceptance.py \
  tests/test_runner_signals.py tests/test_verifier_acceptance.py -q
```

**Commit boundaries**

1. `Allocate and journal durable run attempts`
2. `Publish terminal failure evidence`
3. `Retry frozen runs with preserved history`
4. `Reference immutable attempt documents from terminal runs`
5. `Exercise cancellation and preemption outcomes`

## Phase 6. Implement benchmark execution

**Contract:** [Benchmark execution](contracts/BENCHMARK_EXECUTION.md).

- [x] Add `ExecuteBenchmarkRequest`, `ExecuteBenchmarkSuccess`, and the
  `execute_benchmark()` application operation.
- [x] Replace `BenchmarkSpec.confirmation_count` with
  `execution_count: Literal[2]`; the count covers one candidate and one
  confirmation.
- [x] Add typed artifact-comparison and metric-criterion receipts to
  `BenchmarkResult`.
- [x] Add the `viper execute-benchmark` command with human and JSON output.
- [x] Verify the candidate run before allocating confirmation attempts.
- [x] Execute the same frozen plan for the one confirmation required by
  `BenchmarkSpec.execution_count`.
- [x] Preserve distinct stage snapshots and attempt-file snapshots for each
  confirmation.
- [x] Recompute every benchmark metric through its Phase 4 dependency contract.
- [x] Compare complete `parameters` and `predictions` artifact descriptions.
- [x] Apply every metric threshold after recomputation and parity checks.
- [x] Construct, publish, and verify `BenchmarkResult` before returning success.
- [x] Exercise passing confirmation, threshold failure, metric mismatch,
  parameter mismatch, prediction mismatch, source mismatch, and reused-attempt
  rejection.

**Focused gate**

```bash
python -m pytest tests/test_benchmark_execution.py \
  tests/test_verifier_acceptance.py tests/test_api.py tests/test_cli.py -q
```

**Commit boundaries**

1. `Execute independent benchmark confirmations`
2. `Publish and verify benchmark results`

## Phase 7. Generalize execution across local and GCE hosts

**Contract:** [Cloud execution](contracts/CLOUD_EXECUTION.md).

### Protocol and runtime

- [x] Add immutable boot-image and machine-image references containing project,
  resource name, and server-defined resource ID.
- [x] Select either provisioning source through `GCEProvisioningRef` on
  requested, resolved, and observed GCE environments.
- [x] Add `PythonEnvironmentSpec` with the exact Python version and normalized,
  sorted installed-distribution mapping.
- [x] Add an authoring helper that resolves the provisioning-source ID before
  freezing; require freezing to preserve the selected immutable identity.
- [x] Generalize preflight from the local-only check to the effective
  environment selected for each stage.
- [x] Add GCE project, provisioning source, machine type, zone, guest OS, kernel, CPU,
  CUDA, driver, and numerical-runtime observation.
- [x] Compare the realized environment with the stage environment override or
  shared run environment selected by the plan.
- [x] Publish the same workspace, snapshots, journal, and terminal run files on
  local and GCE hosts.

### Acceptance

- [x] Exercise deterministic local CPU, local CUDA, GCE CPU, and GCE CUDA
  fixtures.
- [x] Reject provisioning-source, machine-type, accelerator, lockfile, Python
  environment, and numerical-control mismatches.
- [x] Build and install the Phase 7 wheel on the designated L4 VM.
- [x] Execute the maintained acceptance project from the existing SSH terminal
  with `python train.py` and `viper run`.
- [x] Verify the completed GCE run through a clean installed-wheel process.

**Focused gate**

```bash
python -m pytest tests/test_runtime.py tests/test_cloud_execution.py \
  tests/test_preflight.py tests/test_runner_acceptance.py -q
```

**Commit boundaries**

1. `Model immutable GCE boot environments`
2. `Observe and verify GCE runtimes`
3. `Verify in-place GCE execution`

## Phase 8. Freeze the public interface and project scaffold

**Contract:** [Package release](contracts/PACKAGE_RELEASE.md).

### Application and CLI

- [x] Freeze stable error codes for request, retrieval, conflict, execution,
  verification, publication, cancellation, and internal failures.
- [x] Apply the approved redaction policy to serialized failures.
- [x] Canonicalize paths, UTC datetimes, bytes, sets, and mappings in JSON
  results.
- [x] Add golden JSON fixtures for every public success and failure family.
- [x] Route warnings into JSON result models.
- [x] Capture output and exit status for every CLI command in acceptance tests.
- [x] Freeze one `PreflightCheckCode` for every release-gated preflight rule.
- [x] Freeze the operation, schema, capability, decorator, context, and helper
  imports listed in `PUBLIC_API.md`.
- [x] Define the unit, contract, integration, release, live-CUDA, and domain
  validation interface in `PUBLIC_API.md` and `DEVELOPMENT.md`.
- [x] Register strict pytest configuration and require one tier and one domain
  for every test module.
- [x] Package `viper/py.typed` and verify the marker through the public API
  acceptance test.
- [x] Include `retry`, `execute_benchmark`, and `init_project` in application
  dispatch, CLI dispatch, schema discovery, and capability discovery.

### Project scaffold and guides

- [x] Implement `viper init PATH --package PROJECT_PACKAGE` for an absent or
  empty target directory.
- [x] Generate one five-stage example whose repository-relative implementation
  paths work with any project package name and directory layout:

  ```text
  download -> build -> embed -> train -> evaluate
  ```

  The scaffold includes project parameter models, one evaluation metric,
  artifact loaders, and focused project tests. The maintained acceptance driver
  authors one experiment and benchmark after the generated repository receives
  its first source commit.
- [x] Make the generated source freeze, preflight, run, benchmark, and verify
  in its generated form.
- [x] Add concise guides for stage callables, parameter models, HTTP downloads,
  metrics, artifact loaders, retries, benchmarks, and GCE execution.
- [x] Reconcile README, protocol, application API, public API, contract index,
  examples, and this checklist.

**Focused gate**

```bash
python -m pytest tests/test_api.py tests/test_api_json.py \
  tests/test_cli.py tests/test_public_api.py tests/test_project_init.py -q
```

**Commit boundaries**

1. `Freeze VIPER application results and public imports`
2. `Generate a complete VIPER starter project`
3. `Document the installed user path`

## Phase 9. Build and validate the release candidate

### Package metadata

- [x] License the package under Apache License 2.0 and include the canonical
  license text in each distribution.
- [x] Record Peter Driscoll as package author and maintainer with the confirmed
  publication email.
- [x] Confirm the repository and documentation project URLs.
- [x] Set the distribution version to `0.1.0a1`.
- [x] Confirm classifiers and supported Python versions against the tested CI
  matrix.

### Deterministic release gate

- [x] Run the repository gate from a clean checkout at the current candidate.
- [x] Build the source distribution and wheel.
- [x] Run `twine check` on both distributions.
- [x] Install the wheel into clean Python 3.11, 3.12, 3.13, and 3.14
  environments.
- [x] Run every public import, schema, capability, CLI help, and JSON smoke test
  from the installed wheel.
- [x] Create the scaffold outside the VIPER checkout and execute its complete
  local run and benchmark.
- [x] Complete the live GCE acceptance case from the same wheel.
- [x] Require successful remote CI for the exact candidate commit.
- [x] Record every command, result, environment, and distribution digest in the
  release-candidate report.

**Release-candidate gate**

```bash
python -m build
python -m twine check dist/*
```

The release report supplies the clean-environment and GCE commands because
those checks execute outside this repository environment.

**Commit:** `Prepare VIPER 0.1.0a1 release candidate`

## Phase 10. Publish VIPER 0.1.0a1

- [x] Add the dedicated Trusted Publishing workflow for TestPyPI and tagged
  PyPI releases.
- [x] **Owner input:** register `.github/workflows/release.yml` for the
  `testpypi` and `pypi` GitHub environments in both package indexes.
- [x] Register Peter Driscoll's existing ED25519 public key with GitHub as a
  signing key and configure this repository to sign release tags with it.
- [x] Create the signed tag `v0.1.0a1`, verify its signature, and push the tag.
- [x] Confirm that the release workflow accepts the tag signature and publishes
  the validated source distribution and wheel to TestPyPI.
- [x] Install `viper-provenance==0.1.0a1` from TestPyPI in a clean environment.
- [x] Repeat the scaffold, local execution, benchmark, verification, and public
  API smoke tests against the TestPyPI installation.
- [x] Confirm that the TestPyPI file digests equal the release-candidate
  digests.
- [x] **Owner input:** approve the protected `pypi` environment after the
  TestPyPI verification job succeeds.
- [x] Publish those exact files to PyPI.
- [x] Install `viper-provenance==0.1.0a1` from PyPI in a clean environment.
- [x] Repeat the installed-package smoke and complete example tests.
- [x] Publish the final release report with local, CI, GCE, TestPyPI, and PyPI
  results.
- [x] Verify that `main` equals `origin/main` and that `v0.1.0a1` identifies the
  validated source commit recorded in the release report.

## Phase 11. Author the publication procedure

**Purpose:** establish one reusable procedure for preparing, validating, and
publishing a Python package.

- [x] Create `python-package-publication` under the shared skill repository.
- [x] Define gates for repository contents, public imports, metadata,
  documentation, examples, distributions, CI, registry publication, and clean
  installation.
- [x] Require the built wheel and source distribution as validation inputs.
- [x] Compose the procedure with direct prose, nomenclature, impact analysis,
  source grounding, environment activation, Git synchronization, and system
  specification review.
- [x] Validate the skill package and commit it to the local skill repository.

**Completion evidence:** the skill validator and direct-prose checker pass for
the new skill package.

**Commit:** `Add Python package publication skill`

## Phase 12. Freeze module ownership

**Contract:** [Package release](contracts/PACKAGE_RELEASE.md).

- [x] Assign every public entity and operation to one defining module.
- [x] Define the small root package interface used by project code.
- [x] Declare `viper.protocol`, `viper.runner`, `viper.verifier`, and
  `viper.api` retired for 0.1.0a2.
- [x] Preserve serialized document fields and discriminators across the Python
  import refactor.
- [x] Define an installed-wheel import inventory that verifies each documented
  symbol and its defining module during Phase 19.
- [x] Apply the specification-system review gate to the revised release
  contract and record the result.

**Focused gate**

```bash
python tests/contract_audit.py
python -m pytest tests/test_contract_audit.py tests/test_public_api.py -q
```

**Commit:** `Freeze VIPER module ownership`

## Phase 13. Create the public repository

- [x] Create the empty public GitHub repository `pvd232/viper`.
- [x] Initialize `/Users/machina/Developer/ChatGPT/viper` as its local
  checkout.
- [x] Copy the approved package source, tests, workflows, configuration,
  license, and current contract documentation.
- [x] Move package source beneath `src/viper/` and update build and test paths.
- [x] Exclude `tools/`, `prior/`, `sources/`, `archive/`, journals, editor state,
  generated metadata, and the two end-to-end essays and UUID-named image.
- [x] Move enduring contract and package-index checks into tests or CI.
- [x] Verify that the initial commit and `origin/main` identify the same commit.

**Acceptance gate:** the source tree contains only approved public files, the
package imports from `src/viper/`, and the baseline tests run from the new
checkout.

**Commit:** `Create public VIPER repository`

## Phase 14. Decompose the protocol

- [x] Move shared Pydantic foundations to `viper._schema`.
- [x] Move parameter categories and parameter references to
  `viper.parameters`.
- [x] Move stage, experiment, run, artifact, reference, metric, benchmark,
  HTTP, runtime, and resume entities into their approved owner modules.
- [x] Update each caller, schema test, fixture, example, and document in the
  same increment as its moved entities.
- [x] Delete `viper.protocol` after the last consumer moves.
- [x] Confirm that canonical serialized documents remain byte-stable for the
  maintained fixtures.

**Acceptance gate:** a repository search returns zero `viper.protocol` imports;
every public type has one definition; schema and serialization tests pass.

**Commit rule:** one commit per owner module, followed by
`Delete the monolithic protocol module`.

## Phase 15. Decompose execution and verification

- [x] Move public run, retry, and benchmark orchestration to
  `viper.execution`.
- [x] Move public verification operations to `viper.verification`.
- [x] Move bounded helper operations into private modules named for their
  stable responsibility.
- [x] Move child-process entrypoints into `viper._workers`.
- [x] Update public requests, results, CLI dispatch, schemas, tests, and docs in
  the same increment.
- [x] Delete `viper.runner` and `viper.verifier` after their last consumers
  move.

**Acceptance gate:** direct Python execution, CLI execution, retry, benchmark
confirmation, and terminal verification pass through the new owner modules.

**Commit rule:** separate execution and verification commits, followed by one
deletion commit for retired modules.

## Phase 16. Consolidate the application surface

- [x] Assign typed application requests, results, dispatch, schema discovery,
  and capability discovery to `viper.api`.
- [x] Update the CLI and root package to call `viper.api`.
- [x] Delete `viper.application` after its last consumer moves.
- [x] Inventory repeated coordinators, worker launchers, serializers, storage
  adapters, and validation helpers.
- [x] Delete dead code and merge exact-operation duplicates whose inputs,
  outputs, side effects, failure semantics, environment handling, signal
  handling, and persisted evidence match.
- [x] Preserve distinct contracts when any of those properties differ.

The inventory moved the typed operation handlers into `viper._api.handlers`.
The worker launchers, serializers, and storage adapters have different failure
or evidence contracts, so each retains its existing owner.

**Acceptance gate:** one call path owns each public operation, all public JSON
fixtures remain valid, and repository coverage equals or exceeds its recorded
baseline.

**Commit rule:** one application-surface commit, then one bounded cleanup
commit for each proven duplicate family.

## Phase 17. Replace the example suite

- [ ] Delete the fragmentary examples and version-stale persisted examples.
- [ ] Generate one synthetic project through `viper init`.
- [ ] Commit its source, authored specifications, tests, and concise usage
  guide.
- [ ] Execute acquisition, the five-stage candidate plan, benchmark
  confirmation, and terminal verification from the installed wheel.
- [ ] Run the committed example in CI outside the VIPER checkout.

**Acceptance gate:** a new user can install the wheel and complete the entire
documented example using only files contained in the public repository.

**Commit:** `Replace examples with one runnable project`

## Phase 18. Rewrite the public documentation

- [ ] Rewrite the root README around installation, the first verified run, the
  core guarantee, and the complete example.
- [ ] Move the formal protocol to `docs/reference/protocol.md`.
- [ ] Rewrite the technical overview as
  `docs/explanation/how-viper-works.md`.
- [ ] Merge `PUBLIC_API.md` and `APPLICATION_API.md` into
  `docs/reference/api.md`.
- [ ] Move the getting-started guide to
  `docs/tutorials/getting-started.md`.
- [ ] Move versioning to `docs/reference/versioning.md`.
- [ ] Convert `DEVELOPMENT.md` into root `CONTRIBUTING.md` and move detailed
  validation instructions to `docs/development/testing.md`.
- [ ] Keep the approved implementation contracts beneath `docs/contracts/`.
- [ ] Delete obsolete plans, editorial files, end-to-end essays, and the
  UUID-named image.
- [ ] Audit the README, documentation, example prose, metadata, CLI help, and
  release notes with the direct-prose procedure.
- [ ] Validate internal links and PyPI rendering.

**Acceptance gate:** documentation uses the final imports, every command runs,
every internal link resolves, and the direct-prose check passes.

**Commit:** `Rewrite VIPER public documentation`

## Phase 19. Build and validate 0.1.0a2

- [ ] Set the version to `0.1.0a2` and point project URLs to `pvd232/viper`.
- [ ] Verify Apache-2.0, Peter Driscoll's author and maintainer identity,
  classifiers, supported Python versions, dependency bounds, and CLI entry
  points.
- [ ] Run lint, formatting, type checking, unit, contract, integration, and
  release tests from a clean checkout.
- [ ] Build the source distribution and wheel and run `twine check`.
- [ ] Inspect both archives for approved files and metadata.
- [ ] Install the wheel outside the checkout under Python 3.11–3.14.
- [ ] Run the public import inventory, CLI smoke tests, and generated example
  from each supported environment.
- [ ] Require successful CI for the exact candidate commit.
- [ ] Record commands, environments, results, source commit, and distribution
  digests in `docs/releases/0.1.0a2.md`.

**Commit:** `Prepare VIPER 0.1.0a2 release candidate`

## Phase 20. Run live GCE acceptance

- [ ] Provision the designated single-GPU L4 Spot instance with the approved
  deployment script.
- [ ] Install the exact 0.1.0a2 wheel produced in Phase 19.
- [ ] Execute the generated example through CPU and CUDA stage startup and
  terminal verification.
- [ ] Record the machine, accelerator, Python environment, commands, results,
  and wheel digest in the release report.
- [ ] Tear down the ephemeral VM and attached SSD while preserving the backup
  machine image.

**Acceptance gate:** the recorded wheel digest equals the release-candidate
wheel, CPU and CUDA acceptance pass, the terminal run verifies, the ephemeral
resources are deleted, and the backup image remains available.

## Phase 21. Publish VIPER 0.1.0a2

- [ ] Configure the `pvd232/viper` GitHub environments and both registry
  trusted publishers for `.github/workflows/release.yml`.
- [ ] Create and verify the signed tag `v0.1.0a2` on the recorded candidate
  commit.
- [ ] Publish the validated files to TestPyPI.
- [ ] Confirm TestPyPI digests and repeat the clean-install public example.
- [ ] Approve the protected PyPI environment and publish the same files.
- [ ] Confirm PyPI digests and repeat the clean-install public example.
- [ ] Publish the completed release report and GitHub release.
- [ ] Verify that local `main`, `origin/main`, the signed tag, both registries,
  and the release report identify the same source and distribution files.

**Completion gate:** `pip install viper-provenance==0.1.0a2` succeeds in a clean
environment and the installed package completes the public example.

## Deferred work

The following workstreams begin after `0.1.0a2`:

- OCI mounts, network confinement, secret mounts, resource limits, and
  adversarial execution tests.
- Crash adoption across hosts, partial-publication recovery, and durable remote
  object-store publication.
- Multi-GPU distributed execution: assign one child process and CUDA device to
  each rank, initialize the process group, persist rank-local runtime and replay
  state, and verify collective membership.
- Epoch-completion receipts and `OversightPolicy` capability requirements.
- Agent mutation dry-runs and downstream-lineage indexing.
- Additional built-in metrics, loaders, retrieval strategies, and graphical
  interfaces.
