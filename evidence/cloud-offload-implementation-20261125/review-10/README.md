# Review 10: complexity and code count

CFO-REQ-10 remains unmet. Active runtime and test code grew across Viper and JEP.
Deleting superseded proposal copies is useful repository cleanup, but receives no
runtime or test reduction credit here. This review does not assert formal contract
acceptance or replace the functional reviews.

## Counted source

| Repository | Runtime before | Runtime after | Change | Tests before | Tests after | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| VIPER | 35,607 | 40,299 | +4,692 | 32,790 | 37,984 | +5,194 |
| JEP | 36,917 | 36,827 | -90 | 11,130 | 11,271 | +141 |
| Combined | 72,524 | 77,126 | +4,602 | 43,920 | 49,255 | +5,335 |

Viper's remaining change since the user PB05 checkpoint adds
3,514 runtime lines and 5,082 test lines.

Viper is compared with `f659faf7e7d0b721af736520c1b2b201d778c891`.
JEP is compared with `c2f9716e398dd5442ca9d3579dfa788657a6cd00`.
The supplemental Viper checkpoint is `1345473` (resolved in the JSON).
Current heads, uncommitted counted paths, every counted file's SHA-256 and line
count, baseline blob identities, and the counting rule are in [counts.json](counts.json).

Runtime means Viper's `src/viper` Python files and JEP's root-level Python files
plus `csts_pilot`, `jep_pilot` and `scripts`. Tests include Python helper and
configuration modules under each repository's `tests`. The same scope is used
before and after. Existing nonignored new files are counted; deleted paths are not.
Documentation, evidence, dependency manifests and planning copies are excluded.

## Ownership review

The new owners have distinct responsibilities. The registry owns current locations,
preferences and pending-source protection. Durable operation/job files own publication
intent and collection closure. Immutable copy and individual-file proofs certify
whole snapshots and individual payloads respectively. Their registry entries are
hash-checked indexes, rather than another publication or retention decision.
`LocalArtifactStore` owns ordinary resolution. Cleanup applies current policy through
the registry and the same reader locks.

JEP's independent `csts_pilot/background_storage.py` queue was removed. Its displaced
queue tests were removed as well; replacement native integration tests are included
in the totals. No planning-copy deletion is represented as that runtime retirement.

The ignored worker `--store` input and the `PublicationSession.identifier` synonym
are now removed. Two bounded consolidation opportunities remain: share operation
file-selection merging, and share provider metadata checks without conflating fresh
full-byte verification with reuse of an existing verified proof. These could remove
dozens of lines, not the thousands needed to make the present totals negative.
No large refactor or deletion of meaningful checks is recommended to game the count.

## Boundary

This agent inspected source and performed read-only Git/blob and filesystem counts.
It did not run tests or change application code. Source hashes were rechecked before
writing this evidence. Recount if any counted source changes. Dependency pins and
formal contract completion remain outside this count.
