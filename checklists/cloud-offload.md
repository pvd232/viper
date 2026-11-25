# Cloud Offload Checklist

The [typed workspace](cloud-offload.toml) owns package registration, repository checkouts and requirement placement. The [contract](../contracts/cloud-offload.md) owns the guarantee. The [current work summary](../plans/cloud-offload/QUEUE.md) reports implementation and validation state.

Native publication, resolution, recovery and cleanup are implemented. The final fast gate passes at `df10a3e`: Ruff checks and formatting, Pyrefly with zero errors, and 805 tests plus 11 subtests, with 4 skips. All 227 selected integration cases pass across retained bounded runs, including all 27 README cases; [the coverage record](../evidence/cloud-offload-integration-20261125/coverage.json) maps each selected case to retained evidence. Hosted PR checks are still running; no CI success is claimed. No formal acceptance or completion receipt is asserted.

| Phase | Requirements | Work |
| --- | --- | --- |
| 1 | CFO-REQ-01, CFO-REQ-02 | Original identities and durable complete inventories. |
| 2 | CFO-REQ-03, CFO-REQ-04, CFO-REQ-05 | Shared resolution, preferences and managed readers. |
| 3 | CFO-REQ-06, CFO-REQ-07 | Native workflow lifetime and background publication. |
| 4 | CFO-REQ-08, CFO-REQ-09, CFO-REQ-10 | Cleanup, recovery and cross-repository consolidation. |

PB01–PB05 foundations were user-applied at checkpoints `7e7d981` and `1345473`. Later work is autonomous under the user's updated instruction. Source implementations and meaningful tests are active for the native publication/resolution path; PB07 cleanup and its worker observers are active. The final fast gate and all 227 selected integration cases pass. Hosted PR checks are still running.

**CFO-REQ-10 is OPEN.** Current maintained Viper/JEP totals do not satisfy net reduction. Removing obsolete full-file planning mirrors is recorded separately and cannot satisfy that runtime/test condition.

The actual JEP checkout is `jep-native-offload`, bound in the typed workspace. Its final commit `d44073e296a638944a83684e9635d9b7fffc104f` pins Viper `df10a3e2258a28d7eb276d5a35a5621c0384a694`. Drafts [Viper PR 24](https://github.com/pvd232/viper/pull/24) and [JEP PR 26](https://github.com/pvd232/JEP/pull/26) carry the changes. [PB09 retained evidence](../plans/cloud-offload/CFO-PB-09/jep/proposal.json) records its exact candidate and source/test counts. [The observer amendment](../evidence/revisions/cloud-offload-observer-bindings-20261125/README.md) preserves the prior contract and corrects planned test names without changing requirements or acceptance conditions.

The [maintained-code report](../evidence/cloud-offload-implementation-20261125/review-10/README.md) records combined runtime 72,524 to 77,510 (+4,986) and tests 43,920 to 49,697 (+5,777), including the frozen Viper source at `df10a3e`. These figures exclude planning copies, documentation and evidence. They supersede the earlier +9,937 snapshot and leave CFO-REQ-10 unmet.

The final source-membership repair preserves Git commit/path verification after offload. Its private proofs use the existing registry and auxiliary snapshot transport. The identity/recovery observer bindings include the ordinary queue/evict/import path and reject unrelated cached source even when its declared SHA matches. No requirement, acceptance condition or block dependency changes.

Retained final logs: [Viper fast gate](../evidence/cloud-offload-implementation-20261125/validation/make-check.log), [JEP CPU suite](../evidence/cloud-offload-implementation-20261125/validation/jep-tests.log), and [JEP Pyrefly](../evidence/cloud-offload-implementation-20261125/validation/jep-pyrefly.log). Viper reports 805 passing tests, 11 passing subtests and 4 skips; JEP reports 47 passing tests and 4 subtests. These results do not close the unmet reduction condition.
