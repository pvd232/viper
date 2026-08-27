# VIPER contract-system audit

## Decision

The mechanical audit passes. All ten contracts pass the schema, value-lifecycle,
traceability, counterexample, and propagation gates. Parameters, stage
invocation, process startup, HTTP retrieval, artifact validation, metric
provenance, attempt execution, benchmark execution, and cloud execution are
implemented. The 0.1.0a2 package-release revision is approved for
implementation.

## Reviewed scope

The review covers the ten contracts indexed by [README.md](README.md), the
[formal protocol](../ProvenanceS1_v3.md), the
[application API](../APPLICATION_API.md), the [public API](../PUBLIC_API.md),
the [master checklist](../PUBLICATION_TODO.md), the active `viper` package, and
the test suite. The audit result applies to the complete document set in the
Git commit containing this report.

Historical material under `archive/` and reference material under `prior/`
remain outside the active design state.

## Mechanical results

`python tests/contract_audit.py` reports:

| Check | Result |
|---|---:|
| Active contracts | 10 |
| Python blocks parsed | 74 |
| Repeated classes compared | 49 |
| Repeated aliases compared | 8 |
| Implemented Pydantic schemas generated | 136 |
| Named verifier rules traced to the checklist | 63 |
| Deterministic result | Pass |

The comparison checks class decorators, bases, fields, annotations, defaults,
constraints expressed through field declarations, and repeated aliases.

## Repaired findings

| Finding | Repair |
|---|---|
| The stage receipt digest named the live runtime context while verification reconstructed a serialized binding. | `StageContextBinding` now owns `context_digest`; runtime handles and absolute paths remain in the dataclass. |
| A successful stage referenced an invocation receipt before that receipt had an immutable identity. | The execution sequence now publishes the invocation receipt first and constructs `ResolvedStageInvocationRef` before the stage snapshot. |
| Invocation outcomes omitted cancellation and preemption. | `StageInvocationReceipt.outcome` now covers all four child outcomes. |
| One URL could return new bytes under the same experimental plan. | `HttpRequestSpec` now fixes the expected SHA-256 and byte count; discovery publishes changing content for later selection. |
| HTTP status evidence was optional while status acceptance was mandatory. | Every successful transport now returns `ObservedHttpResponse`. |
| External executable discovery occurred after transport execution. | `ProjectHttpTransportSpec` now freezes executable byte identities; preflight verifies them before invocation. |
| The executable version label lacked a universal verification operation. | The enforced claim now uses executable SHA-256 and byte count. |
| Redirected credentials lacked an origin authorization boundary. | Credential references now contain normalized authorized origins. |
| Dynamic follow-up retrievals could introduce bytes absent from the frozen experimental plan. | Experimental download stages now contain one fixed retrieval per input; pagination and scraping belong to discovery. |
| Metric timing created separate public spec classes. | One `MetricSpec.mode` now selects `recompute` or `live`. |
| Metric recomputation stored a runtime digest while omitting its source evidence. | Each metric worker now contributes a complete `MetricExecutionReceipt`; `environment_digest` is removed. |
| The child initialized and recorded named NumPy generators, then omitted them from `StageContext`. | `StageContext.numpy_generators` carries the initialized objects; `StageContextBinding.numpy_generator_names` and `ProcessStartupReceipt.generators` preserve their identities and initialized-state digests. |
| Metric worker receipts lacked the run and attempt that owned their measurements. | Both `MetricExecutionReceipt` values now contain the embedded measurement's run and attempt identities. |
| The benchmark contract showed a one-field class as a complete definition. | The contract now displays the full `BenchmarkSpec`. |
| Retry eligibility was implicit. | VIPER 0.1 accepts failed and cancelled runs and rejects successful runs. |
| Stored pointer files were required to contain the commit that would later contain their consuming benchmark. | Each `StoredInputRef` now preserves the pointer file's own immutable commit; source-owned code and lockfiles remain bound to `RunSpec.source.commit`. |
| Public API prose retained the superseded HTTP and metric interfaces. | Both API documents now use required responses, preflight executables, metric modes, and dedicated workers. |
| Public entities shared one monolithic protocol module and several operation modules with overlapping public responsibilities. | The 0.1.0a2 package contract assigns each entity and operation to one defining module and requires deletion of the retired source modules after migration. |

## Value lifecycles

| Value | Producer | First available | Runtime form | Persisted form | Verifier reconstruction |
|---|---|---|---|---|---|
| Validated stage parameters | Parameter worker | Plan freeze and child startup | Project `ParameterSet` subclass | Stage params plus `parameter_digest` | Load the frozen class and validate the same mapping |
| Stage context binding | Coordinator | Before child launch | `StageContextBinding` | Invocation receipt | Rebuild from the run, attempt, stage, inputs, retrieval handles, artifacts, metric IDs, and configured NumPy generator names |
| Live stage context | Child | Immediately before callable invocation | Frozen dataclass with paths and handles | None | Verify its serialized binding and invocation receipt |
| Invocation outcome | Coordinator | Child termination | Terminal child result | `StageInvocationReceipt` | Load the attempt-owned receipt and compare it with attempt state |
| Startup controls | Coordinator and child | Process launch and control application | Environment and library state | `ProcessStartupReceipt` | Derive expected values from `RunSpec` and query recorded runtime evidence |
| Named NumPy generator | Child | Generator initialization | `numpy.random.Generator` in `StageContext.numpy_generators` | Binding name plus initialization receipt | Match the binding names with the frozen controls and named receipt set |
| HTTP body | Selected transport | Transport completion | Assigned destination path | `ResolvedHttpRetrieval.body` | Retrieve bytes and compare request and resolved identities |
| HTTP response | Selected transport | Transport completion | `ObservedHttpResponse` | `ResolvedHttpRetrieval.response` | Apply the frozen accepted-status and persisted-header rules |
| Artifact representation | Stage publisher | Stage completion | File or directory | `ResolvedArtifact` in the stage snapshot | Retrieve every member and verify path, SHA-256, and byte count |
| Metric dependencies | Runner | Producing stage completion | Verified paths | `ResolvedMetricDependency` entries | Resolve the declared stage values and compare complete file identities |
| Metric worker execution | Metric worker | Worker completion | Value plus runtime observations | `MetricExecutionReceipt` | Match run, attempt, stage, and metric identities with the embedded measurement |
| Attempt result | Coordinator | Terminal attempt transition | Attempt state | `RunAttempt` and `ResolvedAttemptRef` | Replay the journal and verify every referenced evidence file |
| Benchmark result | Benchmark executor | Confirmation completion | Artifact and metric comparisons | `BenchmarkResult` | Recompute parity, thresholds, and final status from referenced evidence |
| GCE runtime | Stage child | Runtime observation | Host and backend observations | Resolved environment plus `ExecutionContext` | Compare with the effective stage environment |

## Requirement traceability

| Contract | Declaring input | Runtime operation | Persisted evidence | Verification | Acceptance |
|---|---|---|---|---|---|
| Parameters | `ParameterModelRef` and stage params | Load exact class and validate strictly | Frozen refs and parameter mapping | `parameter_model.identity`, `parameter_model.validation` | Reject changed class bytes and invalid fields |
| Stage invocation | `StageImplementationRef` and `StageContextBinding` | Invoke the exact callable once | Invocation receipt and references | Six `stage.*` and parameter checks | Deliver `epochs=3`; reject a changed binding |
| Process startup | Run controls and effective environment | Launch child, apply controls, and deliver named generators | Startup receipt, context binding, and execution context | Ten `startup.*` checks | Exercise generator delivery, CPU, one CUDA device, and distributed rejection |
| HTTP retrieval | Request, policy, transport, expected body | Invoke selected transport | Resolved retrieval and body | Fourteen HTTP, parameter, stage, and artifact checks | Exercise HTTPX, project transport, redirect, credential, and tamper cases |
| Artifact validation | Artifact and loader refs | Enumerate, materialize, and load | Resolved artifact | Five `artifact.*` checks | Exercise files, bundles, loader failure, and resume-state validation |
| Metric provenance | Metric spec and dependencies | Execute production and verification workers | Measurement and run-owned worker receipts | Eight `metric.*` checks | Exercise recomputed evaluation, worker ownership, and live training metrics |
| Attempt execution | Frozen run and terminal event | Allocate, journal, close, and publish | Run attempt and evidence refs | Eight `attempt.*` checks | Fail attempt 1, retry as attempt 2, and preserve attempt 1 |
| Benchmark execution | Benchmark spec and candidate run | Execute one independent confirmation | Benchmark result and comparison receipts | Five `benchmark.*` checks | Pass one confirmation; reject altered predictions |
| Cloud execution | Effective GCE environment | Execute on active VM and observe it | Resolved environment and execution context | Eight environment, GCE, runtime, and result checks | Accept matching L4 VM; reject machine and package drift |
| Package release | Versioned distribution and public inventory | Build, install, scaffold, execute, and publish | Distributions and release report | Distribution and import-ownership gates | Run the generated project from clean local and GCE installations; reject a symbol with a second defining module |

## Counterexamples

| Contract | Smallest false-positive execution | Rejecting check after completion |
|---|---|---|
| Parameters | The stage mapping validates through a different class with the same symbol. | `parameter_model.identity` |
| Stage invocation | The callable receives `epochs=2` while the frozen stage contains `epochs=3`. | `parameter.value` |
| Process startup | The binding names `augmentation`, while the callable receives an empty NumPy generator mapping. | `startup.context` |
| HTTP retrieval | The endpoint returns same-length bytes with a different digest. | `http.content` |
| Artifact validation | One bundle member changes while the loader still returns successfully. | `artifact.representation` |
| Metric provenance | The recomputation receipt selects another attempt while retaining the original measurement. | `metric.measurement` |
| Attempt execution | A stage fails and the coordinator exits before publishing the terminal attempt. | `attempt.terminal` |
| Benchmark execution | The confirmation reuses the candidate attempt or its stage snapshot. | `benchmark.confirmation` |
| Cloud execution | The run executes on another machine type. | `gce.machine_type` |
| Package release | One documented symbol imports from two defining modules. | Installed-wheel import-ownership gate |

## Propagation findings

The contract layer, formal protocol, application API, public API, checklist,
implementation, verifier, and tests agree for the published 0.1.0a1 release.
The approved 0.1.0a2 revision has one implementation sequence in the master
checklist:

| Approved surface | Current implementation |
|---|---|
| Module ownership | Move each public entity to its approved owner and delete the retired modules. |
| Public repository | Create `pvd232/viper` with the approved source, tests, documentation, example, and release configuration. |
| Release validation | Build 0.1.0a2, verify its imports and contents, install it across supported Python versions, and run the exact wheel on the designated L4 host. |
| Publication | Publish matching files to TestPyPI and PyPI, then repeat the public example from clean installations. |

## Contract decisions

| Contract | Decision |
|---|---|
| Parameters | Implemented |
| Stage invocation | Implemented |
| Process startup | Implemented |
| HTTP retrieval | Implemented |
| Artifact validation | Implemented |
| Metric provenance | Implemented |
| Attempt execution | Implemented |
| Benchmark execution | Implemented |
| Cloud execution | Implemented |
| Package release | Approved |

## Validation

The final review gate must rerun:

```bash
python tests/contract_audit.py
python -m pytest tests/test_contract_audit.py -q
ruff check tests/contract_audit.py tests/test_contract_audit.py
pyright --pythonpath "$(command -v python)"
git diff --check
```
