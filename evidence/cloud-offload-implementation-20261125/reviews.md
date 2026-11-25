# Independent implementation reviews

The root reconciled ten actual collaboration-agent reviews. These are scoped local
code-review results, not posted GitHub reviews or formal protocol acceptance.
Rechecks below overlap; their counts must not be summed into a suite total. Earlier
findings were retained in the conversation and repaired in PB06, PB07 and PB08.

| Reviewer | Scope and repaired findings | Final scoped result |
| --- | --- | --- |
| review_01_registry_and_locks | Reader protection before resolution and memo reads, standalone fetcher lifetime, current/foreign namespace locks, single-join binding lookup, file versus snapshot proofs | Approved. 19 focused cases passed. |
| review_02_durable_queue | Worker launch/observation, retries, missing worker recovery, target inheritance, rate-limit isolation, collection merge, final retry accounting, root-only launcher and operation_id cleanup | Approved. Final simplification: five focused cases and worker CLI passed. |
| review_03_native_execution | Outer workflow ownership, exact target mismatch, restoration for cloud-only upload sources, native path-based reuse and unchanged synchronous behavior | Approved. Six focused cases plus cloud-only and explicit-target observers passed. |
| review_04_storage_and_recovery | Foreign multi-file adoption and locks, binding-query cost, shared cache inode, Git expected identities, verified export reads | Approved. Twelve focused cases passed; 32-member lookup used 32 binding queries rather than 1,024. |
| review_05_cleanup_and_retention | One deletion predicate, complete publication proofs, exact ownership, last-reader retry and stable mixed keep/offload decisions | Approved after both deferred-cleanup counterexamples were repaired. Three focused regressions, Pyrefly and Ruff passed. |
| review_06_workers_and_outputs | Logical versus physical output access, streaming checkpoint hashing, shared-hardlink ctime changes, exact replacements, ready uploads before cleanup | Approved. Seven focused checks passed. Later mixed-policy repair is covered by reviewer 05. |
| review_07_jep_workflows | Native refs in callers, current publication locator precedence, frozen record preservation and absent live-output traces | Approved. Three focused cases and both original locator counterexamples passed. |
| review_08_jep_generation_recovery | Current allocation/operation/receipt pairing, current versus historical proofs, attached identity, cached ACK authorization and independent cloud-copy verification | Approved. 44 affected cases plus stale-pairing and exact-copy counterexamples passed. |
| review_09_public_api_and_contract | Public publication locators/output paths, exact cloud reads, native/legacy documentation and real verifier bindings | Approved. Public JSON observers and five admission/publication guards passed. Its initial 50 active bindings became 53 when worker-cleanup observers were added. |
| review_10_minimal_design_skeptic | Authority ownership, retired JEP queue and final maintained source/test counts | CFO-REQ-10 unmet. No competing authority found; combined maintained code grew by 9,937 lines. See review-10/. |

Reviewer approvals bind their inspected byte-level slices. The later PB08 removal
of ignored launch inputs was separately inspected by reviewer 02. Canonical observer
metadata and actual broad validation are separate evidence owners. No live cloud
roundtrip, campaign or infrastructure operation was performed for these reviews.

## Final source identity amendment

Reviewers 03 and 04 independently demonstrated that an unrelated cached payload
could satisfy a stale declared SHA at a pinned Git commit/path. The repair carries
commit/tree proofs beside source payloads using existing auxiliary snapshots and
registry indexes. It adds no public receipt fields or transfer queue.

Reviewers 01 through 04 approved their final affected slices. Reviewer 03 passed
16 focused tests plus the poisoned-cache rejection through four entry routes.
Reviewer 04 passed 16 independent source/import observations and inspected the
final hot-cache optimization. Reviewer 02 also found and verified the explicit
owner-close context repair, including conservative callback failure recovery.

The final eight-line destination inventory reuse repair was separately approved
by reviewer 04. All five existing manifest cases passed without changing their
identity rejection assertions. The final maintained-code count is +10,763 lines,
so reviewer 10's reduction finding remains open.
