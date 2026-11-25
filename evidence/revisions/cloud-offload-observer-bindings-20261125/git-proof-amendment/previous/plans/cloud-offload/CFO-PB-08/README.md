# CFO-PB-08

**Requirements:** CFO-REQ-03, CFO-REQ-06, CFO-REQ-09, CFO-REQ-10

**Depends on:** PB07

**Status:** Functional consolidation is under review; the required maintained-code reduction is OPEN and unmet.

Viper uses one inventory validator, ordinary resolver, registry retention authority and final deletion decision. Ordinary fetchers share the store rather than owning another persistent payload cache. Explicit promotion and bounded transfer staging remain supported.

Obsolete cumulative source, test and diff mirrors PB02–PB07 have been retired after their changes landed. Their removal is housekeeping, counted separately from runtime/test reduction. Current source and meaningful checks remain in Git. Preserve historical declaration/review evidence with its exact revision boundary.

Functional observations include tests/test_shared_storage.py and the native workflow/recovery/cleanup suites. They cannot establish the separate net-reduction condition. The final report must show maintained Viper and JEP source/tests separately and combined. Current combined growth fails CFO-REQ-10, whose claim and acceptance conditions are unchanged.

Source changes and ordinary test logs are distinct from formal acceptance. No lifecycle receipt is created by this document.

## Frozen maintained-code count

[Review 10's source-hashed report](../../../evidence/cloud-offload-implementation-20261125/review-10/README.md) uses immutable original baselines and the frozen working trees. It excludes planning copies, documentation, evidence and dependency manifests.

| Repository | Runtime before | Runtime after | Change | Tests before | Tests after | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Viper | 35,607 | 40,299 | +4,692 | 32,790 | 37,984 | +5,194 |
| JEP | 36,917 | 36,827 | -90 | 11,130 | 11,271 | +141 |
| Combined | 72,524 | 77,126 | +4,602 | 43,920 | 49,255 | +5,335 |

Combined maintained runtime and tests grew by 9,937 lines. CFO-REQ-10 remains OPEN and unaccepted. The 41,761 retired planning-mirror lines receive no credit against this requirement.
