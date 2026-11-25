# Cloud Offload Implementation Status

The user applied the initial blocks by hand, then authorized autonomous completion. The active source tree is now the implementation authority. Historical prepared files and review reports describe their own revisions only.

| Blocks | Current work |
| --- | --- |
| PB01–PB03 | User-applied identity, registry, shared resolver and reader foundations at `7e7d981`. |
| PB04–PB05 | User-applied retention and captured-original publication at `1345473`, with later repair work retained in the candidate. |
| PB06 | Native workflow/session, durable upload admission, detached worker, portable recovery and child-reader integration are implemented; broad repair validation is underway. |
| PB07 | Single-decision cleanup and its worker ordering, reader-retry and mixed-policy tests are active; final validation is pending. |
| PB08 | End-to-end evidence and duplicate-owner retirement are underway. PB02–PB07 obsolete preparation mirrors have been retired separately from maintained runtime/test size. |
| PB09 | JEP native adapter is implemented in the bound `jep-native-offload` worktree; retained bounded validation passes. Cross-repository reduction remains unmet. |

Native integration is committed at `1b8ed60`, its recovery repair at `c869ea6`, and cleanup at `95a2420`. Final broad and integration validation remain pending.

## Current validation boundary

The final broad Viper gate and independent repair rechecks are pending. Ten initial independent reviews are reported complete by the integration owner, with repairs still underway. No formal PairBlock acceptance or completion receipt is asserted. [The observer-binding amendment](../../evidence/revisions/cloud-offload-observer-bindings-20261125/README.md) records actual definitions rather than creating test aliases.

The JEP retained CPU log reports 44 passing cases and 4 subtests at its own candidate; its Pyrefly logs report no errors. Those controlled-boundary checks establish adapter behavior and do not establish a live cloud deployment or the entire Viper contract.

## Acceptance still open

CFO-REQ-10 requires maintained source/test reduction for Viper and JEP separately and combined. The frozen count snapshot records total maintained source/test growth in both repositories. The requirement and its acceptance conditions stay unchanged and OPEN. Removing obsolete planning mirrors cannot make this condition pass. [The retained count report](../../evidence/cloud-offload-implementation-20261125/review-10/README.md) records Viper runtime +4,692 and tests +5,194; JEP runtime -90 and tests +141; combined +9,937 maintained lines. Counts describe the frozen working trees, including migrated JEP edits still outside its baseline commit.

Existing standalone cloud-return and explicit complete-keep APIs retain their waits. Within the native workflow, upload and cleanup remain queued independently of scientific results. Pending sources and local data must remain available until verified publication or verified durable handoff.

## Retained results before the final broad gate

- The prior PB06 focused gate recorded 752 passing tests, 11 passing subtests and 4 skips. Later repair source still requires its final gate.
- [The real fresh-workspace producer test](../../evidence/cloud-offload-integration-20261125/fresh-producer-10333.txt) passed in 200.24 seconds. It deletes the original producer directory, verifies the original Git commit is absent locally, forbids remote Git access, imports verified publication evidence and restores unchanged artifact references. Its cloud provider is controlled in-memory.
- [The retirement inventory](../../evidence/revisions/cloud-offload-observer-bindings-20261125/retired-mirrors.json) lists 102 obsolete planning files removed from 16 trees. Their 41,761 lines are excluded from maintained runtime/test reduction. PB01 and all historical before-images remain unchanged.
