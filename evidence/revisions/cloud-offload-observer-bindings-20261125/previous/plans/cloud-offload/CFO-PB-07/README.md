# CFO-PB-07

**Status:** planned; complete deletion implementation and executable PairBlockPlan not yet frozen.

**Requirements:** CFO-REQ-05, CFO-REQ-08, CFO-REQ-09

**Depends on:** PB06

Context: Cleanup eligibility must be decided when a worker removes a file, while root completion only admits deferred work. Connect the same durable work mechanism to one fresh deletion decision without blocking computation or removing files needed by later admitted consumers.

## Owned targets

- src/viper/retention.py
- src/viper/_storage_registry.py
- src/viper/_storage_locks.py
- src/viper/execution/_publication.py and the PB06 worker entry point
- src/viper/execution/_materialization.py
- src/viper/execution/_restore.py

## Contribution

At actual successful outer closure, enqueue identities for cleanup reconsideration and return without awaiting uploads, receipts or deletion. Offload permits removal; it never requires eviction at a child call return. Use the same queue/progress owner; no separate retention service. Pending cleanup must not occupy a worker waiting for a dependency or reader while ready upload work is queued behind it. Wake/reconcile deferred work through the existing mechanism, without a tight polling loop.

The worker requires genuine successful closed-root evidence, closed final inventory, complete verified objects/receipts at every admitted target, current subscriber permission, no pending source obligation or admitted consumer, reader exclusion and an exact owned physical binding. Obtain the content exclusion lock and recheck policy and the actual file under one short registry transaction before unlink/retirement. Hash/transfer/network verification never runs under that transaction. Queue requests cannot contain irrevocable path deletion or a cached allowed boolean.

Use already committed proof on later cleanup without a new upload, final receipt mutation or repeated full remote verification. Keep, busy readers and pending proof are normal deferrals, not publication failures. Preserve one usable local copy for keep while allowing redundant owned views to be cleaned. Preserve user exports and replaced files. Route legacy eviction and recursive managed-directory removal through the same predicate; scratch retains its task owner.

## Observing checks

- tests/test_offload_workflow.py: runner returns with cleanup pending; ready publication progresses past blocked cleanup; child completion, failed batches, pending targets, newer keep, readers and replacements prevent stale deletion.
- tests/test_offload_recovery.py: cleanup uses completed proof without reopening upload or changing a receipt; source protection persists across worker absence.
- tests/test_retention.py: all legacy/recursive managed deletion uses the same current decision.

These are planned checks. No placeholder implementation or test body is supplied.

## Gate and stop condition

Freeze complete actions from the real PB06 commit, run Pyrefly before focused CPU/mock and native process tests, require semantic documentation/schema checks, then non-mutating Ruff checks. Stop on guessed success, incomplete proof, stale policy, replacement deletion or a legacy bypass. Keep cleanup disabled until the actual predicate and required connectors pass.
