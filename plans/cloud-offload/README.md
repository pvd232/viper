# Cloud Offload Working Documents

Use the active source tree and [current work summary](QUEUE.md) for this implementation. The user moved from guided typing to autonomous completion. Complete source changes belong in Git; old full-file proposal mirrors are obsolete after application.

| Document | Purpose |
| --- | --- |
| [Contract](../../contracts/cloud-offload.md) | Unchanged guarantee and current implementation owners. |
| [Canonical package](../../contracts/cloud-offload.toml) | Stable requirements, real observing tests and block dependencies. |
| [Checklist](../../checklists/cloud-offload.md) | Requirement placement and validation state. |
| [Observer amendment](../../evidence/revisions/cloud-offload-observer-bindings-20261125/README.md) | Exact before-image, test-binding corrections and static audit. |

PB01–PB05 contain the guided history. [PB06](CFO-PB-06/README.md) owns native admission and workflow integration. [PB07](CFO-PB-07/README.md) owns worker cleanup. [PB08](CFO-PB-08/README.md) owns Viper consolidation and acceptance evidence. [PB09](CFO-PB-09/README.md) owns JEP caller migration.

Implementation, executed checks, independent review and formal acceptance are separate claims. Current broad validation and repair rechecks are underway. CFO-REQ-10 remains open because maintained source/test net reduction has not been met.
