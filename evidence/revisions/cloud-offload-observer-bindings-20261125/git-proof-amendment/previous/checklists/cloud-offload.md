# Cloud Offload Checklist

The [typed workspace](cloud-offload.toml) owns package registration, repository checkouts and requirement placement. The [contract](../contracts/cloud-offload.md) owns the guarantee. The [current work summary](../plans/cloud-offload/QUEUE.md) reports implementation and validation state.

Native publication, resolution, recovery and cleanup are implemented in the active candidate. Final broad validation and independent repair rechecks are still in progress. No formal acceptance or completion receipt is asserted.

| Phase | Requirements | Work |
| --- | --- | --- |
| 1 | CFO-REQ-01, CFO-REQ-02 | Original identities and durable complete inventories. |
| 2 | CFO-REQ-03, CFO-REQ-04, CFO-REQ-05 | Shared resolution, preferences and managed readers. |
| 3 | CFO-REQ-06, CFO-REQ-07 | Native workflow lifetime and background publication. |
| 4 | CFO-REQ-08, CFO-REQ-09, CFO-REQ-10 | Cleanup, recovery and cross-repository consolidation. |

PB01–PB05 foundations were user-applied at checkpoints `7e7d981` and `1345473`. Later work is autonomous under the user's updated instruction. Source implementations and meaningful tests are active for the native publication/resolution path; PB07 cleanup and its worker observers are active. Final gate and repair recheck results remain pending.

**CFO-REQ-10 is OPEN.** Current maintained Viper/JEP totals do not satisfy net reduction. Removing obsolete full-file planning mirrors is recorded separately and cannot satisfy that runtime/test condition.

The actual JEP checkout is `jep-native-offload`, bound in the typed workspace. [PB09 retained evidence](../plans/cloud-offload/CFO-PB-09/jep/proposal.json) records its exact candidate and source/test counts. [The observer amendment](../evidence/revisions/cloud-offload-observer-bindings-20261125/README.md) preserves the prior contract and corrects planned test names without changing requirements or acceptance conditions.

The [final maintained-code report](../evidence/cloud-offload-implementation-20261125/review-10/README.md) records combined runtime 72,524 to 77,126 (+4,602) and tests 43,920 to 49,255 (+5,335). These figures exclude planning copies, documentation and evidence. They leave CFO-REQ-10 unmet.
