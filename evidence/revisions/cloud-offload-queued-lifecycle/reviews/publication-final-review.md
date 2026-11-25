# Queued lifecycle cross-review

**Verdict: APPROVE_SCOPED.** No routine behavior blocker found in the reviewed
contract declarations, PB06/PB07 targets/contributions, or the corrected PB03/
PB04 resolver successors. This is source review of proposed code and planned
requirements, not application, execution readiness, or runtime validation.

## Reviewed declaration scope

- `contracts/cloud-offload.toml`, SHA-256
  `e2172d80c4e1da49429266241d17b663119a5b47de8ca3bf67a103c9ac8355b9`
- `contracts/cloud-offload.md`, SHA-256
  `c4abf6443dc1f720540e5ac8588a44d22eb4a9e8c0c4bc5d2214474a928c4f1f`
- PB06 README, SHA-256
  `de3aa6a6c765e12a718cadd37bd165da4eec1cce529b2c4353b53f01bea7fb40`
- PB07 README, SHA-256
  `5c8d14ef59838e33cf1461c57d37782538eb73bfe5d062c79486ea2de4596dfe`

The declarations correctly distinguish immediate local durable admission from
background network transfer, verification, final receipts and cleanup. They
cover authoring before draft execution, prior-run pointers, stage/attempt/final/
benchmark records and borrowed ownership across native worker boundaries.
Publication is queued with offload enabled or disabled. A source obligation
survives worker absence, and a blocked cleanup cannot head-of-line block ready
uploads. Scientific status and immutable run bytes remain separate from durable
publication status. Explicit verified-cloud-return and complete-keep waits are
preserved. No caller-owned transfer pool joins the runner on return.

PB06/PB07 remain explicitly planned with observing checks; they do not pretend
that the missing native queue or closure receipt already exists. Cleanup uses
the same durable mechanism and the actual fresh registry decision. No separate
retention service, speculative future-use inference or duplicated receipt/
location authority is introduced.

## Reviewed resolver scope

The final corrected files are present in staged PB03/PB04:

- PB03 `replace/src/viper/storage.py`, SHA-256
  `3c7442ba21d2ecb88f6581e195a766cec7e7c647c2ee8d386b4b3b32d1388862`
- PB04 `replace/src/viper/storage.py`, SHA-256
  `c0dc8b0669d2ce5c5d2cb4602f9dab47272f3b55f885f49c7b83d22777768d2b`

`_register_snapshot` registers membership and rereads the authoritative registry
before `_resolve` selects a payload. This correctly includes existing equal-
content original aliases on the first admission of a new snapshot. The earlier
empty-locations return is corrected in both full-file successors.

Fresh ordinary fetchers pass lazy provider factories, consult registered local
aliases before shared cached bytes, and instantiate a service only when needed.
Active-workspace bindings precede legacy absolute workspace lookup; malformed
metadata is not converted into an unregistered fallback. Content checks remain
with the existing verifier and inventory validator.

An actual HF payload miss selects the provider's existing streaming restore
branch before its verified temporary-file/atomic-installation path. This avoids
a second persistent Hub payload copy without changing the global HF default.
Task-owned transfer caches remain independent and do not borrow ordinary local
payloads to claim remote verification. Provider and session ownership are not
moved into registry transactions.

I also read the proposed first-admission equal-content-original test and the
actual HF provider/mock-HTTP streaming tests. They observe the intended ordinary
reuse/restore behavior; I did not execute them. Existing fixture propagation and
logical-reference documentation successors are being reviewed separately and
are not implicitly approved by this report.

## Explicit limits

No Python/application/test/gate commands, cloud requests, active repository edits
or implementation application were performed. File reads, diffs/hashes and this
scoped report are the review evidence. Source approval does not claim the
unimplemented queue, whole-workflow final receipt or automatic cleanup passes.
