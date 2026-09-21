# Execution Path Parity

## 1. Status

**Contract status:** Complete in the [Execution storage protocol](../checklists/execution-storage-protocol.md) checklist.

<!-- contract-protocol:generated:start -->
**Complete.**

**Checklist:** [Execution storage protocol](../checklists/execution-storage-protocol.md)

### PairBlocks

<a id="epp-pb-01"></a>

#### <nobr><code>EPP-PB-01</code></nobr>

**Status:** complete

**Requirement contribution:** Remove storage-destination-dependent StageContext input and output path overrides while preserving declared materialization rules.

<a id="epp-pb-02"></a>

#### <nobr><code>EPP-PB-02</code></nobr>

**Status:** complete

**Requirement contribution:** Publish declared local paths to cloud snapshots and update metrics, verification, retention, and tests to observe the restored path contract.

**Dependencies:** <nobr><code>EPP-PB-01</code></nobr>

### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>EPP-REQ-01</code></nobr> | For the same RunSpec, StageContext.outputs must expose the same declared workspace-relative output paths when StorageSettings.destination is local and when it is viper_cloud. | complete | <nobr><code>EPP-VR-01</code></nobr> | <nobr><code>EPP-PB-01</code></nobr> |
| <nobr><code>EPP-REQ-02</code></nobr> | For the same RunSpec, StageContext.inputs must not change because StorageSettings.destination changes; same-run future inputs, stored inputs, external inputs, and download-stage outputs must use their declared materialization rules without a cloud-only path override. | complete | <nobr><code>EPP-VR-02</code></nobr> | <nobr><code>EPP-PB-01</code></nobr> |
| <nobr><code>EPP-REQ-03</code></nobr> | Cloud-backed runs must publish the files written at the declared StageContext paths to sealed cloud snapshots under the same logical SnapshotFileRef.path values used by local runs, while retaining storage_destination_changed protection for an existing run. | complete | <nobr><code>EPP-VR-03</code></nobr> | <nobr><code>EPP-PB-02</code></nobr> |
| <nobr><code>EPP-REQ-04</code></nobr> | Recomputed metrics, file-access receipts, retention, and verification must consume declared stage input and output paths after path parity is restored; no verifier may require cloud-only scratch output paths. | complete | <nobr><code>EPP-VR-04</code></nobr> | <nobr><code>EPP-PB-02</code></nobr> |
| <nobr><code>EPP-REQ-05</code></nobr> | Each execution-path-parity PairBlock must receive a code review before completion; the review must inspect the changed execution files, changed tests, retained path invariant, and validation evidence. | complete | <nobr><code>EPP-VR-05</code></nobr> | <nobr><code>EPP-PB-02</code></nobr> |

### Verification rules

| Rule | Requirements | Acceptance conditions | Success case | Rejection cases |
|---|---|---|---|---|
| <nobr><code>EPP-VR-01</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr> | A paired local and cloud run records the same path string for a stage callable's observed context.outputs entry and publishes the same artifact SnapshotFileRef.path. | [test_cloud_run_exposes_declared_output_paths_to_stage_context](../tests/test_run_execution.py) | [test_cloud_run_rejects_destination_dependent_output_context_paths](../tests/test_run_execution.py) |
| <nobr><code>EPP-VR-02</code></nobr> | <nobr><code>EPP-REQ-02</code></nobr> | A downstream stage that reads a same-run producer artifact observes the same context.inputs path under local and cloud destinations, and a download stage writes its declared output path before publication. | [test_cloud_run_exposes_destination_independent_input_paths](../tests/test_run_execution.py) | [test_download_publication_rejects_cloud_only_output_materialization](../tests/test_execution_acceptance.py) |
| <nobr><code>EPP-VR-03</code></nobr> | <nobr><code>EPP-REQ-03</code></nobr> | The in-memory cloud provider receives sealed snapshot files whose paths match the declared output paths, and an existing run still rejects a changed storage destination. | [test_cloud_snapshot_uses_declared_paths_after_context_path_parity](../tests/test_run_execution.py) | [test_run_destination_is_bound_to_first_execution](../tests/test_storage.py) |
| <nobr><code>EPP-VR-04</code></nobr> | <nobr><code>EPP-REQ-04</code></nobr> | Recomputed metrics read the declared artifact paths, file-access receipts admit declared paths and reject undeclared writes, retention verifies cloud-backed files, and protocol tests contain no cloud-only output path contract. | [test_cloud_recomputed_metric_reads_declared_artifact_path](../tests/test_run_execution.py) | [test_stage_file_access_rejects_undeclared_write](../tests/test_stage_file_access.py) |
| <nobr><code>EPP-VR-05</code></nobr> | <nobr><code>EPP-REQ-05</code></nobr> | The PairBlock handoff contains a code-review decision that names every changed execution file, every changed test file, the path invariant, and the passing gate receipt. | [EPP-PB-01 review handoff](../contracts/execution-path-parity.md#epp-pb-01) | [missing code-review decision](../contracts/execution-path-parity.md#epp-pb-02) |
<!-- contract-protocol:generated:end -->

## 2. Claim

VIPER must expose the same `StageContext.inputs` and `StageContext.outputs` paths for a given `RunSpec` regardless of whether `[storage].destination` is `local` or `viper://...`.

The storage destination selects where VIPER publishes immutable run evidence. The storage destination must not change the file paths passed to user stage functions through `StageContext`.

## 3. Resolved Gap

### Observed pre-repair path

1. `OutputSpec.path` stores the run-owned logical output path, and `run_output_path()` constructs paths shaped as `artifacts/<stage_id>/<output_name>/<relative_path>` in [outputs.py](../src/viper/outputs.py).
2. `execute_attempt()` reads `[storage].destination` through `load_storage_settings()` and binds that destination for the run in [execution/_attempt.py](../src/viper/execution/_attempt.py).
3. `_stage_output_paths()` returns `None` for `LocalStorageDestination`, but returns `.viper/workspaces/<run_id>/attempt-<attempt_id>/stages/<stage_id>/outputs/<artifact_name>/<relative_path>` for cloud destinations in [execution/_attempt.py](../src/viper/execution/_attempt.py).
4. `execute_stage_process()` writes those cloud-only paths into `StageWorkerContext.physical_outputs` in [execution/_stage.py](../src/viper/execution/_stage.py).
5. The stage worker validates that `StageContextBinding.outputs` equals the declared logical paths, then replaces those paths with `StageWorkerContext.physical_outputs` before constructing `StageContext` in [viper/_workers/stages.py](../src/viper/_workers/stages.py).

### Repaired connector

`StageContextBinding.outputs` verifies the declared output paths, and `viper._workers.stages.main()` builds `StageContext.outputs` from those paths for every storage destination. `StageWorkerContext` has no `physical_outputs` field.

### Rejected counterexample

A stage declares `model = output(path="artifacts/train/model/model.pt", ...)`. With local storage, the callable receives `context.outputs["model"] == root / "artifacts/train/model/model.pt"`. With cloud storage, `_stage_output_paths()` makes the callable receive `context.outputs["model"] == root / ".viper/workspaces/<run_id>/attempt-1/stages/train/outputs/model/model.pt"`. Both executions can publish a cloud snapshot whose `SnapshotFileRef.path` is `artifacts/train/model/model.pt`, so existing verification can pass while the public stage path contract differs.

### Retained evidence

`test_cloud_run_exposes_declared_output_paths_to_stage_context` records local and cloud `StageContext.outputs` values from stage code. `test_cloud_run_exposes_destination_independent_input_paths` records the same-run producer input path under cloud storage.

### Disposition

Gap resolved. `StageContext.inputs` and `StageContext.outputs` are destination-independent for a fixed `RunSpec`, while cloud publication, destination binding, snapshot verification, run retention, and recomputed metrics remain valid.

## 4. Minimal Sufficient Design

The selected design extends the existing publisher path and removes the destination-dependent stage-context path override.

| Candidate | Decision | Reason |
|---|---|---|
| Reuse current cloud override | Reject | `_stage_output_paths()` changes the paths visible to user code. |
| Extend publication from declared paths | Select | `ViperCloudSnapshotPublisher.publish()` already accepts `{logical_path: source_path}`; declared paths can serve as both `logical_path` and `source_path` after the stage writes them. |
| Add a mount, sync, or copy layer | Reject | A second execution path would add another local path authority and another recovery surface. |
| Stop | Reject | RICO and benchmark commands depend on destination-independent `inputs` and `outputs` paths. |

The selected design keeps `OutputSpec.path`, `StageContextBinding.outputs`, `SnapshotFileRef.path`, `ViperCloud.publish()`, and `GcsProvider.publish_revision()` as the owning primitives. It removes the cloud-only meaning from `StageWorkerContext.physical_outputs`.

## 5. Regression Inventory

This contract recognizes these destination-dependent path regressions and review surfaces. Each row names the pre-repair code that created or accepted the regression and the exact observation required for closure.

| Regression | Pre-repair code link | Required review evidence |
|---|---|---|
| Cloud execution gives a stage callable a different `context.outputs` path than local execution for the same declared output. | [`_stage_output_paths()` creates cloud-only output paths](../src/viper/execution/_attempt.py#L106); [`execute_attempt()` passes those paths to `execute_stage_process()`](../src/viper/execution/_attempt.py#L586); [`execute_stage_process()` serializes them as `physical_outputs`](../src/viper/execution/_stage.py#L451); [`viper._workers.stages.main()` passes `physical_outputs` into `StageContext.outputs`](../src/viper/_workers/stages.py#L352). | A paired local/cloud test records the same observed `context.outputs["<artifact>"]` path and the code review verifies that no storage destination branch can alter `StageContext.outputs`. |
| Cloud execution materializes same-run future inputs under `.viper/workspaces/.../inputs/...` instead of the producer's declared artifact path. | [`resolve_inputs()` accepts `materialize_future_inputs_to_workspace`](../src/viper/execution/_materialization.py#L148); [the cloud branch rewrites `materialized_path`](../src/viper/execution/_materialization.py#L194); [`execute_attempt()` enables that branch for non-local destinations](../src/viper/execution/_attempt.py#L498). | A downstream-stage test records the same observed future-input path under local and cloud storage and the code review verifies the future-input path comes from the producer `OutputSpec.path`. |
| Cloud download stages write final output artifacts under `.viper/workspaces/.../stages/.../outputs/...` instead of the declared output path. | [`retrieve_download_inputs()` accepts `materialize_outputs_to_workspace`](../src/viper/execution/_materialization.py#L310); [the cloud branch creates `physical_destination`](../src/viper/execution/_materialization.py#L350); [`publish_download_body()` accepts `physical_destination`](../src/viper/execution/_downloads.py#L15); [`execute_attempt()` enables that branch for non-local destinations](../src/viper/execution/_attempt.py#L452). | A download-stage test verifies the final artifact path is the declared output path before publication and the code review verifies HTTP temporary custody remains separate from final artifact materialization. |
| Recomputed metrics read cloud scratch artifact paths through `artifact_paths_override`, so metric behavior depends on storage destination. | [`run_after_stage_metrics()` accepts `artifact_paths_override`](../src/viper/execution/_metric.py#L257); [the override replaces `_artifact_paths(root, stage)`](../src/viper/execution/_metric.py#L288); [`execute_attempt()` passes cloud `output_paths`](../src/viper/execution/_attempt.py#L740). | A recomputed-metric test verifies metric code reads the declared artifact path under cloud storage and the code review verifies the override is removed or no longer storage-destination-dependent. |
| Worker context includes `physical_outputs` as a serialized path channel that can override declared outputs. | [`StageWorkerContext.physical_outputs`](../src/viper/execution/_stage.py#L99); [`execute_stage_process()` writes it](../src/viper/execution/_stage.py#L451); [`viper._workers.stages.main()` reads it](../src/viper/_workers/stages.py#L352). | Code review confirms `physical_outputs` is removed or cannot affect declared stage outputs. |
| Existing tests encode cloud-only path behavior as accepted behavior rather than rejecting it. | [`tests/test_run_execution.py` cloud-native run tests](../tests/test_run_execution.py#L1794); [`tests/test_execution_acceptance.py` physical download destination tests](../tests/test_execution_acceptance.py#L27); [`tests/test_protocol.py` workspace input path fixture](../tests/test_protocol.py#L1259); [`tests/test_worker.py` workspace path fixture](../tests/test_worker.py#L69). | Tests are updated to reject destination-dependent public paths and the code review names every changed test. |

## 6. Affected Surfaces

| File | Required change |
|---|---|
| [execution/_attempt.py](../src/viper/execution/_attempt.py#L106) | Remove `_stage_output_paths()` or make it destination-independent. Stop setting `materialize_outputs_to_workspace` and `materialize_future_inputs_to_workspace` from the storage destination. Stop passing `artifact_paths_override` to recomputed metrics for cloud output paths. |
| [execution/_stage.py](../src/viper/execution/_stage.py#L87) | Stop serializing cloud-only output paths into `StageWorkerContext.physical_outputs`. Keep physical input support only where an input declaration explicitly selects attempt-owned materialization. |
| [viper/_workers/stages.py](../src/viper/_workers/stages.py#L347) | Build `StageContext.outputs` from `StageContextBinding.outputs` for every storage destination. |
| [execution/_materialization.py](../src/viper/execution/_materialization.py#L148) | Preserve destination-independent input materialization for future, stored, external, and download inputs. |
| [execution/_downloads.py](../src/viper/execution/_downloads.py#L15) | Remove `physical_destination` from final artifact output publication or constrain it to non-public temporary HTTP body custody. |
| [execution/_metric.py](../src/viper/execution/_metric.py#L257) | Remove cloud-only `artifact_paths_override` dependence after declared output paths are restored. |
| [storage.py](../src/viper/storage.py#L399) | Retain `ViperCloudSnapshotPublisher.publish()` and `publish_resolved_files()` as the storage backend boundary. |
| [cloud.py](../src/viper/cloud.py#L160) | Retain provider-neutral publication. |
| [gcs.py](../src/viper/gcs.py#L294) | Retain sealed revision publication and manifest verification. |
| [workspace.py](../src/viper/workspace.py#L163) | Retain attempt custody paths for captured inputs and control files; do not use those paths as a cloud-only replacement for declared stage outputs. |

## 7. Test Inventory

| File | Required observation |
|---|---|
| [tests/test_run_execution.py](../tests/test_run_execution.py#L1794) | Paired local/cloud runs observe identical `StageContext.outputs` and destination-independent same-run input paths. Cloud snapshots retain declared `SnapshotFileRef.path` values. Recomputed metrics read declared artifact paths. |
| [tests/test_execution_acceptance.py](../tests/test_execution_acceptance.py#L27) | Download publication rejects a final artifact path contract that requires cloud-only output materialization. |
| [tests/test_worker.py](../tests/test_worker.py#L69) | Worker context tests no longer treat `.viper/workspaces/.../outputs/...` as the public output path. |
| [tests/test_protocol.py](../tests/test_protocol.py#L1259) | Protocol fixtures stop encoding cloud-only stage output paths as a valid public contract. |
| [tests/test_stage_file_access.py](../tests/test_stage_file_access.py#L433) | File-access receipts admit declared input/output paths and reject undeclared writes. |
| [tests/test_storage.py](../tests/test_storage.py#L1022) | Destination binding still rejects a changed destination for an existing run. |
| [tests/test_retention.py](../tests/test_retention.py#L168) | Retention verifies cloud-backed files without assuming a cloud-only stage output path. |

## 8. Mandatory Code Review

Every PairBlock in this contract requires a code review before completion. The review must inspect the exact changed files, the retained path invariant, the generated or manual tests, and the gate receipt. A PairBlock is incomplete until its handoff records a review decision.

| PairBlock | Review scope |
|---|---|
| `EPP-PB-01` | `execution/_attempt.py`, `execution/_stage.py`, `viper/_workers/stages.py`, `execution/_materialization.py`, `execution/_downloads.py`, and the tests that observe `StageContext.inputs` and `StageContext.outputs`. |
| `EPP-PB-02` | `execution/_metric.py`, `storage.py`, `cloud.py`, `gcs.py`, verification, retention, and every test that proves cloud publication still records declared `SnapshotFileRef.path` values. |

### Code Review Decision

Decision: pass.

Reviewed implementation files: [execution/_attempt.py](../src/viper/execution/_attempt.py), [execution/_stage.py](../src/viper/execution/_stage.py), [viper/_workers/stages.py](../src/viper/_workers/stages.py), [execution/_materialization.py](../src/viper/execution/_materialization.py), [execution/_downloads.py](../src/viper/execution/_downloads.py), and [execution/_metric.py](../src/viper/execution/_metric.py).

Reviewed test files: [tests/test_run_execution.py](../tests/test_run_execution.py) and [tests/test_execution_acceptance.py](../tests/test_execution_acceptance.py).

Invariant reviewed: `StageContext.outputs` comes from `StageContextBinding.outputs`; same-run future inputs materialize to the producer `OutputSpec.path`; download artifacts materialize to their declared `OutputSpec.path`; recomputed metrics read `_artifact_paths(root, stage)`.

Residual risk: external and stored inputs can still use attempt-workspace custody paths when their input declaration selects that behavior. That path is input-declaration-dependent, not storage-destination-dependent.

Stale override scan: `rg -n "_stage_output_paths|materialize_future_inputs_to_workspace|materialize_outputs_to_workspace|artifact_paths_override|physical_outputs|physical_destination" src tests` returns no matches.

## 9. Enforcement Chain

| Requirement | Implementation owner | Verifier |
|---|---|---|
| `EPP-REQ-01` | `execute_attempt()`, `execute_stage_process()`, and `viper._workers.stages.main()` | `EPP-VR-01` |
| `EPP-REQ-02` | `resolve_inputs()`, `retrieve_download_inputs()`, and `stored_input_path()` | `EPP-VR-02` |
| `EPP-REQ-03` | `ViperCloudSnapshotPublisher.publish()`, `ViperCloud.publish()`, and `GcsProvider.publish_revision()` | `EPP-VR-03` |
| `EPP-REQ-04` | `run_after_stage_metrics()`, `StageFileAccessObserver`, verification, and retention | `EPP-VR-04` |
| `EPP-REQ-05` | PairBlock handoff and review evidence | `EPP-VR-05` |

## 10. Accepted and Rejected Executions

Accepted execution: a run declares `artifacts/train/model/model.pt`; local and cloud execution both pass `root / "artifacts/train/model/model.pt"` to `context.outputs["model"]`; the cloud run publishes that file under `SnapshotFileRef.path == "artifacts/train/model/model.pt"`; verification fetches the cloud object and checks its digest and byte count.

Rejected execution: a cloud run passes `root / ".viper/workspaces/<run_id>/attempt-1/stages/train/outputs/model/model.pt"` to `context.outputs["model"]` for the same `RunSpec`; `EPP-VR-01` fails because the stage callable observed a destination-dependent public path.

## 11. PairBlock Scope

`EPP-PB-01` owns the execution-path repair. `EPP-PB-02` owns cloud publication, metrics, file-access, verification, retention, and test convergence after the stage context path repair lands.

## 12. Validation Receipt

Pyright:

```bash
.venv/bin/pyright src/viper/execution/_attempt.py src/viper/execution/_stage.py src/viper/execution/_materialization.py src/viper/execution/_downloads.py src/viper/execution/_metric.py src/viper/_workers/stages.py tests/test_run_execution.py tests/test_execution_acceptance.py
```

Result: `0 errors, 0 warnings, 0 informations`.

Behavior tests:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_execution_acceptance.py tests/test_worker.py tests/test_protocol.py::test_external_inputs_are_local_only tests/test_protocol.py::test_download_models_use_runner_owned_hierarchy tests/test_stage_file_access.py::test_declared_access_rejects_undeclared_write tests/test_stage_file_access.py::test_verifier_rejects_invalid_file_access_receipts tests/test_storage.py::test_bind_run_destination_is_idempotent_and_rejects_change tests/test_retention.py::test_evicts_only_verified_cloud_backed_run_artifacts tests/test_run_execution.py::test_cloud_native_run_returns_and_persists_one_terminal_reference tests/test_run_execution.py::test_cloud_run_exposes_declared_output_paths_to_stage_context tests/test_run_execution.py::test_cloud_run_exposes_destination_independent_input_paths tests/test_run_execution.py::test_cloud_snapshot_uses_declared_paths_after_context_path_parity tests/test_run_execution.py::test_cloud_recomputed_metric_reads_declared_artifact_path
```

Result: `28 passed in 74.52s`.

Ruff:

```bash
.venv/bin/ruff format --check src/viper/execution/_attempt.py src/viper/execution/_stage.py src/viper/execution/_materialization.py src/viper/execution/_downloads.py src/viper/execution/_metric.py src/viper/_workers/stages.py tests/test_run_execution.py tests/test_execution_acceptance.py
.venv/bin/ruff check src/viper/execution/_attempt.py src/viper/execution/_stage.py src/viper/execution/_materialization.py src/viper/execution/_downloads.py src/viper/execution/_metric.py src/viper/_workers/stages.py tests/test_run_execution.py tests/test_execution_acceptance.py
```

Results: `8 files already formatted`; `All checks passed!`.
