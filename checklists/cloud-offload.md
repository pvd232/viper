# Cloud Offload Checklist

The [typed workspace](cloud-offload.toml) owns registration, bindings and requirement placement. The [contract](../contracts/cloud-offload.md) owns the guarantee; [the queue](../plans/cloud-offload/QUEUE.md) owns the current guided handoff.

**Evidence state:** user-approved declarations and proposed code are under source review. Contract/workspace/plan metadata validation is distinct from application validation. No implementation gate, accepted block or lifecycle completion receipt is asserted.

| Phase | Requirements | Work |
| --- | --- | --- |
| 1 | CFO-REQ-01, CFO-REQ-02 | Immutable identity and durable inventory. |
| 2 | CFO-REQ-03, CFO-REQ-04, CFO-REQ-05 | Original-first shared resolution, retention and admitted readers. |
| 3 | CFO-REQ-06, CFO-REQ-07 | Explicit outer workflow and all-native durable background publication. |
| 4 | CFO-REQ-08, CFO-REQ-09, CFO-REQ-10 | Queued live cleanup, recovery, completion guarantees and consolidation. |

The user has typed PB01 foundations/tests, PB02 production foundations and PB03 cache/lock primitives. The next code step is PB03 resolver wiring. Complete PB02–PB05 proposed files are reconciled with guided fixes; application checks remain deferred. PB06–PB09 remain planned targets/checks until full connected code and actual dependency baselines exist.

[Original expansion history](../evidence/revisions/cloud-offload-storage-policy/README.md) and [queued-lifecycle revision history](../evidence/revisions/cloud-offload-queued-lifecycle/README.md) preserve previous declarations and production-computed impact. These planning records establish no historical acceptance or successful publication.
