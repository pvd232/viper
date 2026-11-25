# Review 10: final complexity and code count

CFO-REQ-10 remains unmet. Active runtime and test code grew across Viper and JEP.
Superseded proposal retirement receives no runtime or test reduction credit.
This is count evidence and a bounded ownership review, not formal contract acceptance.

## Counted source

| Repository | Runtime before | Runtime after | Change | Tests before | Tests after | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| VIPER | 35,607 | 40,683 | +5,076 | 32,790 | 38,426 | +5,636 |
| JEP | 36,917 | 36,827 | -90 | 11,130 | 11,271 | +141 |
| Combined | 72,524 | 77,510 | +4,986 | 43,920 | 49,697 | +5,777 |

Viper's remaining change since the user PB05 checkpoint adds
3,898 runtime lines and 5,524 test lines.

Original baselines are Viper `f659faf7e7d0b721af736520c1b2b201d778c891` and
JEP `c2f9716e398dd5442ca9d3579dfa788657a6cd00`. The supplemental Viper baseline
is `1345473`, resolved to its full commit in [counts.json](counts.json).

Viper's counted scope matches the frozen commit
`51630a5b5d03e9964da2a8d1b66f91bd4a55b9e2`.
JEP's counted scope matches source freeze
`e2285b8bfa03bae1c8076f731c541f6a2504f049`; subsequent dependency
and documentation pins do not change the counted Python files.
The JSON records current heads, clean/dirty counted paths, every counted file's
SHA-256 and line count, immutable baseline blob identities, and both source digests.

Runtime means Viper's `src/viper` Python files and JEP's root-level Python files
plus `csts_pilot`, `jep_pilot` and `scripts`. Tests include Python helpers and
configuration modules under each `tests` directory. Scope and counting rules are
the same before and after. Nonignored new files are counted; deleted paths are not.
Documentation, evidence, manifests and planning copies are excluded.

## Distinct owners and retired duplication

The registry owns current inventory, locations, preferences and pending-source
protection. Durable operation/job files own publication intent and closure, rather
than retaining cached permission to delete. Immutable proofs certify whole snapshots,
individual cloud payloads, or Git commit/path membership. Their registry entries are
hash-checked indexes. Ordinary payload resolution has one store owner, and cleanup
uses current policy with the same reader locks.

The Git membership repair adds a small pure [proof owner](../../../src/viper/_git_proof.py).
Generic byte identity cannot establish which file belongs to a pinned Git commit and
path. These proofs use the existing registry and snapshot transport; they add neither
another queue nor a public receipt field.

The [shared graph reader](../../../src/viper/_graph.py) reuses the former promotion
traversal for native enrollment. The [native worker](../../../src/viper/execution/_offload_worker.py)
replaces JEP's independent `csts_pilot/background_storage.py` queue. That deleted
runtime file and displaced queue tests are identified separately in the JSON;
replacement tests remain included in the totals.

The ignored worker `--store` input and `PublicationSession.identifier` synonym are
removed. Two bounded simplifications remain: shared operation file-selection merging,
and shared provider metadata checks that retain the distinction between new byte
verification and an already committed proof. They could remove dozens of lines,
not the thousands needed to make these totals negative. No large refactor or deletion
of meaningful checks is recommended merely to change the count.

## Boundary

This agent reread the immutable baseline blobs and current source hashes. Counted
files were checked again before evidence was written. No tests were run and no
application code or Git state was changed by this recount. Functional verification
and formal contract completion are separate. Recount if any counted source changes.
The evidence-only generating helper is preserved under
`/tmp/viper-review10-recount-20261125.py`.
