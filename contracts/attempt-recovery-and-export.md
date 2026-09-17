# Attempt Recovery and Run Export

## 1. Status

**Contract status:** Planned in the [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md) checklist.

<!-- contract-protocol:generated:start -->
**In progress.** [Jump to current PairBlock](#are-pb-02)

**Checklist:** [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md)

### PairBlocks

<a id="are-pb-01"></a>

#### <nobr><code>ARE-PB-01</code></nobr>

**Status:** complete

**Requirement contribution:** Expose structured failed-attempt results and reuse verified completed stages when the same immutable run is retried.

**Review handoff**

**What changed**

- RunError retains the failed terminal RunResult, whose latest attempt exposes completed and failed stage IDs.
- retry() verifies the prior failed terminal record, searches attempts newest-to-oldest for each eligible completed stage, and republishes those stages through the existing StageReuseReceipt path.
- Verification retains per-attempt stages, inputs, and reuse receipts so repeated retries preserve a fully verified provenance chain without weakening byte, plan, input, metric, or snapshot checks.
- Attempt allocation releases the run lock on every setup failure, including invalid prior-attempt evidence.
- Acceptance tests cover partial results, preflight failure, process skipping, earlier-attempt recovery, repeated retries, lock release, tamper rejection, and the existing reuse and retention paths.

**Plan deviations:** No deviations from ARE-REQ-01 or ARE-REQ-02. Run failure remains exception-based; retry reuses existing stage and metric evidence without changing stage placement or stateless function interfaces.

**Start review:** [Open tested GitHub comparison](https://github.com/pvd232/viper/compare/b235b821b786e4f3fb84665cbc3291234df07775...471cb4a413172f6cfe3be3811ffb9b757274482c)

**Review these files**

- [Complete failed-attempt resume candidate](../plans/attempt-recovery-and-export/ARE-PB-01/patches/failed-attempt-resume.patch#L1)
- [Attempt execution owner](../src/viper/execution/_attempt.py#L120)
- [Reuse verification owner](../src/viper/verification.py#L199)

**Evidence:** [Passing gate receipt](../evidence/gates/are-pb-01-v3.json)

**Decision:** <nobr><code>ARE-PB-01</code></nobr> is complete; no further decision is required.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/attempt-recovery-and-export/ARE-PB-01/plan.toml)

**Retained patch:** [patches/failed-attempt-resume.patch](../plans/attempt-recovery-and-export/ARE-PB-01/patches/failed-attempt-resume.patch)

**Implementation roots:** [pyproject.toml](../pyproject.toml) · [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>AUG-PB-01</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyright src/viper/evidence.py src/viper/execution/_attempt.py src/viper/execution/_reuse.py src/viper/execution/errors.py src/viper/execution/results.py src/viper/reuse.py src/viper/verification.py tests/test_retention.py tests/test_run_execution.py)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_run_execution.py::test_run_error_exposes_partial_attempt_result tests/test_run_execution.py::test_preflight_failure_exposes_no_completed_stage tests/test_run_execution.py::test_retry_reuses_completed_stage_from_failed_attempt tests/test_run_execution.py::test_retry_rejects_tampered_completed_stage tests/test_run_execution.py::test_retry_setup_failure_releases_run_lock tests/test_run_execution.py::test_retry_reuses_completed_stage_across_repeated_failures tests/test_run_execution.py::test_retry_finds_completed_stage_before_empty_failed_retry tests/test_run_execution.py::test_two_stage_local_run_writes_and_verifies_terminal_result tests/test_run_execution.py::test_verified_reuse_skips_stage_process tests/test_verification_acceptance.py::test_stage_reuse_rejects_each_severed_relationship tests/test_protocol.py::test_stage_reuse_models_form_valid_completion_union tests/test_retention.py)
# documentation
(cd . && ruff check --select D src/viper/evidence.py src/viper/execution/_attempt.py src/viper/execution/_reuse.py src/viper/execution/errors.py src/viper/execution/results.py src/viper/reuse.py src/viper/verification.py tests/test_retention.py tests/test_run_execution.py)
# lint
(cd . && ruff format --check src/viper/evidence.py src/viper/execution/_attempt.py src/viper/execution/_reuse.py src/viper/execution/errors.py src/viper/execution/results.py src/viper/reuse.py src/viper/verification.py tests/test_retention.py tests/test_run_execution.py)
# lint
(cd . && ruff check src/viper/evidence.py src/viper/execution/_attempt.py src/viper/execution/_reuse.py src/viper/execution/errors.py src/viper/execution/results.py src/viper/reuse.py src/viper/verification.py tests/test_retention.py tests/test_run_execution.py)
```

</details>

<a id="are-pb-02"></a>

#### <nobr><code>ARE-PB-02</code></nobr>

**Status:** drafting

**Requirement contribution:** Export successful and failed terminal runs as complete, digest-verified offline bundles.

**Plan:** None

**Current receipt:** None

**Dependencies:** <nobr><code>ARE-PB-01</code></nobr>

**Next action:** Run the current PairBlock plan.


### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>ARE-REQ-01</code></nobr> | When run() or retry() raises after allocating an attempt, RunError.result must expose the failed terminal RunResult, its latest RunAttempt, the completed stage IDs, and the failed stage ID without suppressing the exception. | complete | <nobr><code>ARE-VR-01</code></nobr> | <nobr><code>ARE-PB-01</code></nobr> |
| <nobr><code>ARE-REQ-02</code></nobr> | retry() must verify and republish every eligible completed stage from the same run's prior failed attempt, retain a StageReuseReceipt that cites that attempt, and execute only the remaining stages; changed or unverifiable stage evidence must execute again or fail before reuse. | complete | <nobr><code>ARE-VR-02</code></nobr> | <nobr><code>ARE-PB-01</code></nobr> |
| <nobr><code>ARE-REQ-03</code></nobr> | execution.export_run() and viper export-run must write one self-contained bundle containing every record and payload reachable from a terminal successful or failed run, plus a deterministic path, byte-count, and SHA-256 manifest that an offline verifier can validate without the source checkout or VIPER store. | in_progress | <nobr><code>ARE-VR-03</code></nobr> | <nobr><code>ARE-PB-02</code></nobr> |

### Verification rules

| Rule | Requirements | Acceptance conditions | Success case | Rejection cases |
|---|---|---|---|---|
| <nobr><code>ARE-VR-01</code></nobr> | <nobr><code>ARE-REQ-01</code></nobr> | A two-stage run whose second stage fails raises RunError with a failed RunResult whose latest attempt names the first stage as completed and the second as failed. | [test_run_error_exposes_partial_attempt_result](../tests/test_run_execution.py) | [test_preflight_failure_exposes_no_completed_stage](../tests/test_run_execution.py) |
| <nobr><code>ARE-VR-02</code></nobr> | <nobr><code>ARE-REQ-02</code></nobr> | Retrying the failed two-stage run republishes the verified first-stage output through a reuse receipt tied to the prior attempt and invokes only the second stage; changed or corrupted evidence is not reused. | [test_retry_reuses_completed_stage_from_failed_attempt](../tests/test_run_execution.py) | [test_retry_rejects_tampered_completed_stage](../tests/test_run_execution.py) |
| <nobr><code>ARE-VR-03</code></nobr> | <nobr><code>ARE-REQ-03</code></nobr> | Exporting one successful run and one failed run copies every reachable record and payload, records each relative path with its byte count and digest, and passes verification after the source checkout and store are unavailable. | [test_export_run_verifies_offline](../tests/test_export.py) | [test_export_verifier_rejects_missing_or_changed_file](../tests/test_export.py) |
<!-- contract-protocol:generated:end -->

## 2. Claim

VIPER preserves completed work across a failed attempt and can package the complete run record for offline inspection.

## 3. Models

| Model | Role |
|---|---|
| Proposed `RunError.result: RunResult` | Gives the caller the terminal failed run and latest attempt while preserving exception-based failure handling. |
| `RunAttempt.resolved_stages` | Names stages completed before the attempt ended. |
| Proposed `RunResult.completed_stage_ids` and `RunResult.failed_stage_id` | Present the partial outcome directly from the latest attempt. |
| `StageReuseReceipt` | Proves which earlier attempt and stage supplied each republished output. |
| Proposed `RunExportManifest` | Lists every exported relative path, byte count, and SHA-256 digest. |

## 4. Execution

1. A run publishes each completed stage before starting its successor.
2. If a later stage fails, VIPER publishes the failed attempt and terminal run, attaches their `RunResult` to `RunError`, and leaves the exception visible.
3. `retry()` verifies eligible completed stages from the prior attempt, republishes them into the new attempt with reuse receipts, and runs the remaining stages.
4. `execution.export_run()` or `viper export-run` traverses the terminal record and copies every reachable record and payload into a sealed bundle.
5. Offline verification reloads the manifest and checks every path, byte count, digest, and record link.

## 5. Persisted evidence

| Record | Evidence |
|---|---|
| `attempts/<id>/resolved.yaml` | Attempt status, completed stages, invocations, files, and failure. |
| `stages/<stage>/reuse.yaml` | Prior run, attempt, stage, key, and republished file identities. |
| `resolved.yaml` | Terminal run status and attempt references. |
| `<bundle>/manifest.json` | Complete portable file inventory and content identities. |

## 6. Verification

The executable rules require a two-stage failure, a retry that skips the completed first-stage process, corruption rejection, and offline verification of both successful and failed exports.

## 7. Propagation

| Surface | Required change |
|---|---|
| `viper.execution` | Export the run-bundle API and attach structured results to run failures. |
| Attempt execution | Select and verify prior-attempt stages before launching a process. |
| Protocol and verification | Define and verify the export manifest and retry reuse evidence. |
| CLI and docs | Add `export-run` and document partial results, retry, and offline verification. |

## 8. Acceptance case

### Success

Stage A completes, stage B fails, and `RunError.result` reports both facts. A retry republishes A without executing it, executes B, and exports a bundle that verifies after the original store is unavailable.

### Rejection

A changed stage snapshot, missing export payload, altered byte count, or altered digest fails before VIPER claims reuse or a valid bundle.

## 9. Implementation order

1. Add the structured failure result and prior-attempt reuse path.
2. Verify the complete failure-and-retry lifecycle.
3. Add bundle traversal, export, CLI routing, and offline verification.

## 10. Contract-owned PairBlocks

The generated section links the two source-backed implementation blocks and their dependency.

## 11. ContractTarget

Each PairBlock plan owns its exact file actions. The shared runner materializes those actions from the recorded baseline and admits completion only through the declared tests and validation gate.
