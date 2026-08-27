# Attempt execution

## Status

Each local attempt is published as one canonical attempt document with
immutable references to its journal, stage invocations, logs, measurements,
and completed stage snapshots. Explicit retry allocates the next attempt ID
and preserves the earlier attempt history. The runner maps `SIGINT` to
cancellation, maps `SIGTERM` to preemption, and reconciles an abandoned journal
as `coordinator_lost`.

## Required claim

Every invocation of a frozen run plan produces one durable terminal attempt.
Retry creates a new attempt and preserves the evidence from every earlier
attempt.

## Implementation

[`run()`](../../src/viper/execution.py) acquires a run-scoped advisory lock, allocates
the next durable attempt ID, and writes the allocation event before preflight.
Every successful or failed attempt reaches a terminal journal state and enters
the terminal `ResolvedRun`. [`retry()`](../../src/viper/api.py) accepts the
same frozen plan after a failed run and appends the next attempt.

`SIGINT` closes the active attempt as `cancelled`. `SIGTERM` closes it as
`preempted`. Each terminal attempt also writes its canonical
`attempts/<attempt_id>/resolved.yaml` document. After acquiring the released
run lock, the next coordinator closes an abandoned journal with
`coordinator_lost` and allocates a greater attempt ID.

`ResolvedRun.attempts` stores one immutable `ResolvedAttemptRef` for each
canonical attempt document. Real coordinator-process tests deliver `SIGINT`
and `SIGTERM`, then verify the resulting attempt status, typed failure,
journal, logs, active-stage invocation receipt, terminated process group, and
completed-stage prefix.

## Contract models

```python
AttemptFailureCode = Literal[
    "preflight_failed",
    "execution_failed",
    "verification_failed",
    "publication_failed",
    "cancelled",
    "preempted",
    "coordinator_lost",
    "internal_error",
]


class AttemptFailure(ProtocolModel):
    code: AttemptFailureCode
    stage_id: StageId | None
    message: NonEmptyStr
    occurred_at: AwareDatetime


class AttemptJournalRef(ResolvedFileRef):
    kind: Literal["attempt_journal"] = "attempt_journal"


class RunAttempt(ProtocolModel):
    schema_version: Literal[1] = 1
    attempt_id: int = Field(ge=1)
    purpose: Literal["run", "benchmark_confirmation"]
    status: AttemptStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    resolved_stages: tuple[ResolvedStageRef, ...]
    invocations: tuple[ResolvedStageInvocationRef, ...]
    journal: AttemptJournalRef
    measurement_files: tuple[ResolvedFileRef, ...]
    metric_verification_files: tuple[ResolvedFileRef, ...]
    log_files: tuple[ResolvedFileRef, ...]
    failure: AttemptFailure | None


class ResolvedAttemptRef(ResolvedFileRef):
    kind: Literal["resolved_attempt"] = "resolved_attempt"


class ResolvedRun(ProtocolModel):
    schema_version: Literal[1] = 1
    spec: ResolvedRunSpecRef
    status: Literal["succeeded", "failed", "cancelled"]
    attempts: tuple[ResolvedAttemptRef, ...] = Field(min_length=1)
    successful_attempt_id: int | None
    completed_at: AwareDatetime
```

This replaces the current free-text `failure_reason` with one typed failure.
It also makes each completed attempt an independently retrievable immutable
document.

The canonical attempt files are:

```text
experiments/<experiment_id>/runs/<variant_id>/<run_id>/
└── attempts/<attempt_id>/
    ├── resolved.yaml
    ├── journal.jsonl
    ├── measurements/
    │   └── <stage_id>.<metric_id>.jsonl
    ├── metric_verification/
    │   └── <stage_id>.<metric_id>.yaml
    ├── invocations/
    │   └── <stage_id>.yaml
    └── logs/
        ├── <stage_id>.stdout.log
        └── <stage_id>.stderr.log
```

`ResolvedAttemptRef` identifies `resolved.yaml`. That document contains the
`RunAttempt`, including references to the remaining attempt files. The terminal
run stores the ordered references whose purpose is `run`. A benchmark result
stores its `benchmark_confirmation` attempt separately. The verifier retrieves
each attempt through its reference before checking its owning result.

## Allocation and ownership

The coordinator acquires one operating-system-managed advisory lock for the run.
That lock is released automatically when its process exits. The coordinator
then selects:

```text
max(persisted attempt IDs) + 1
```

The persisted IDs come from terminal run history and every attempt journal
beneath the run workspace. The selected ID is written to the durable journal
before preflight or stage execution begins. One coordinator owns one active
attempt. A second coordinator receives a stable ownership failure.

After acquiring a released lock, the coordinator reconciles any prior
nonterminal journal. It closes that attempt as `failed` with failure code
`coordinator_lost`, publishes the available logs and completed stage snapshots,
and then allocates the next ID.

## Terminal outcomes

An attempt closes with exactly one terminal status:

| Status | Meaning |
|---|---|
| `succeeded` | Every stage and terminal publication completed. |
| `failed` | Preflight, execution, verification, or publication failed. |
| `cancelled` | The coordinator acknowledged an explicit cancellation request. |
| `preempted` | The execution host ended the attempt before completion. |

VIPER publishes the attempt journal and available logs for every outcome. A
failed attempt retains every verified stage snapshot completed before failure.
Every started stage also leaves one invocation receipt, including the active
stage that fails, is cancelled, or is preempted.

The coordinator assigns terminal outcomes through these operations:

| Outcome | Evidence-producing operation |
|---|---|
| `cancelled` | The coordinator receives `SIGINT`, records the signal, stops the active child, and closes the attempt. |
| `preempted` | The coordinator receives `SIGTERM`, records the signal, stops the active child, and closes the attempt. |
| `failed` with `coordinator_lost` | A later coordinator acquires the released lock and reconciles an abandoned nonterminal journal. |

An abrupt host loss that prevents terminal publication enters the third path
when a later coordinator performs reconciliation.

The durability claim assumes the attempt workspace and configured store remain
readable and writable. Storage loss belongs to infrastructure recovery. A
surviving nonterminal journal remains sufficient for `coordinator_lost`
reconciliation.

## Retry

Retry receives the same frozen `RunSpec` and allocates the next attempt ID.
Every earlier attempt remains immutable. VIPER 0.1 accepts a terminal
`ResolvedRun` whose status is `failed` or `cancelled`. It rejects a successful
run because benchmark confirmation has its own operation and a changed
experiment requires a new frozen plan.

Benchmark confirmation uses the same allocator and frozen plan with
`purpose="benchmark_confirmation"`. It can follow a successful run attempt and
belongs directly to `BenchmarkResult.confirmation`. `ResolvedRun.attempts`
contains the ordinary run and retry history.

## Verification

| Check | Rule |
|---|---|
| `attempt.order` | Attempt IDs are unique and strictly increasing. |
| `attempt.terminal` | Every published attempt has exactly one terminal status. |
| `attempt.identity` | Each `ResolvedAttemptRef` retrieves bytes whose digest and byte count match the reference and whose attempt ID matches its canonical path. |
| `attempt.files` | The attempt references the published journal, metric-verification files, measurements, and logs from the same attempt. |
| `attempt.failure` | A failed, preempted, or cancelled attempt has one failure value consistent with its journal; a successful attempt has none. |
| `attempt.invocations` | Every started stage has one immutable invocation receipt owned by the attempt. |
| `attempt.retry` | A retry uses the same frozen run plan and a greater attempt ID. |
| `attempt.purpose` | `ResolvedRun.attempts` contain only run attempts; `BenchmarkResult.confirmation` identifies one benchmark-confirmation attempt. |

## Propagation

| Surface | Required change |
|---|---|
| Workspace | Allocate attempt IDs while holding the run lock. |
| Journal | Record allocation and every state transition before the corresponding side effect. |
| Runner | Close every attempt, publish its immutable attempt document, and add its `ResolvedAttemptRef` to the terminal run. |
| Application | Add explicit retry. |
| Verification | Check attempt ordering, terminal state, failure identity, and preserved files. |
| Tests | Exercise a failed first attempt followed by a successful retry. |

## Acceptance case

A three-attempt acceptance case begins with an abandoned attempt `1`. The next
coordinator closes attempt `1` as `coordinator_lost`. Attempt `2` completes
`download` and fails during `train`; VIPER preserves the download snapshot,
both invocation receipts, journal, and failure logs. An explicit retry creates
attempt `3`, completes both stages, and publishes a successful terminal run.

Changing an artifact retained by attempt `2` after attempt `3` has been
published fails file-identity verification.

## Remaining implementation

1. Replace embedded `RunAttempt` values in `ResolvedRun.attempts` with
   `ResolvedAttemptRef` values and make each canonical attempt document the sole
   persisted `RunAttempt` representation.
2. Add real coordinator-process cancellation and preemption acceptance tests.

Cross-host crash adoption, partial-publication recovery, and remote orphan
reconciliation remain deferred beyond VIPER 0.1.
