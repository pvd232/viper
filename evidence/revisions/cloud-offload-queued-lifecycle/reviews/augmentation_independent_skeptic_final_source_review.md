# Independent source review: queued lifecycle augmentation

Verdict: APPROVE_SCOPED for the final reviewed composed proposal sources and
declarations. The corrected legacy test successor and latest alias reload are
now included in the staged packet. This is not an implementation, gate, release
or completion approval.

## Scope and method

Read-only source inspection of the composed candidate under
`/tmp/viper-offload-queued-revision-20261122/staged/`, the latest resolver
author's successors under `resolver/pb03/`, the existing provider interfaces,
and observing test source. No Viper imports, application commands, type checks,
tests, gates or Git mutations were run. The reviewer wrote only this report and
the separately requested proposed references.py file.

## Source identities inspected

| File | SHA-256 |
| --- | --- |
| staged/contracts/cloud-offload.toml (raw bytes) | 8d7533ea57ea0d7dbba8a9590b1525db94e3f124efd994041957d56816aab7c6 |
| staged/contracts/cloud-offload.md | c4abf6443dc1f720540e5ac8588a44d22eb4a9e8c0c4bc5d2214474a928c4f1f |
| staged/PB03 storage.py | 3c7442ba21d2ecb88f6581e195a766cec7e7c647c2ee8d386b4b3b32d1388862 |
| staged/PB03 _source.py | 1083fd48d2be49ca62493978863c435eae8b21aa2515d535ee10825bd807f484 |
| staged/PB03 references.py | f1fd9610ea713c33c33c6a59e2bb2625079151a780d1f40534f4881d7396f3b8 |
| staged/PB03 _storage_locks.py | 23448247618fb9cb0f1392d198d585b619f079e0ecc96b8181e5d1eddfd531a1 |
| staged/PB03 test_storage.py | 4a8f5c40d11dbb7bd5c9feacda461de07168dbcdec8502c76ddf8b84a9524cca |
| staged/PB03 test_shared_storage.py | 1789fa307c50deec3fdb87263f9af0f487223ecefc96bd6dec1ee61fd6920c12 |
| staged/PB03 test_storage_readers.py | 4f0ebc645d35aece76cf7c6c1c177b4525b291f872509701ef819b42176704c5 |
| staged/PB04 storage.py | c0dc8b0669d2ce5c5d2cb4602f9dab47272f3b55f885f49c7b83d22777768d2b |
| staged/PB04 _storage_registry.py | 1328495d0551dd54f29bd994d2aa7c682337a0681d5bbd5cd2028d9eafc10a1c |
| staged/PB04 retention.py | 6d267aeafc645bb2ff0a587173267e5e78a63300fa3ac0df0da19c7844fc702e |
| staged/PB04 test_artifact_retention.py | 844223c256966e996b09f247dd322431f749017013cf0f9a1f734b228f79e5ca |

PB03 and PB04 refer to paths beneath plans/cloud-offload/CFO-PB-03 and
CFO-PB-04 respectively.

## Review results

1. The latest storage successor reloads registered snapshot metadata after first
   registration, so aliases already registered for another snapshot are available
   on the same first resolution. The new-snapshot observing test requires
   returning the existing original with zero payload downloads.
2. RunFetcher supplies lazy provider callbacks. Registered originals and cache
   hits do not construct the cloud client. Its local-store helper checks the
   active registry before opening an original workspace that may no longer exist.
   Listing delegates to the same inventory owner.
3. The ordinary managed HF payload miss selects the existing streaming provider
   branch. It does not require a second permanent Hub checkpoint cache. Bounded
   task-owned verification remains independent and actually downloads.
4. The MemoryCloud test facade now supplies the real inventory, provider and
   verified-path interface. The HF tests use the actual provider's HTTP streaming
   branch with mocked metadata/HTTP, rather than adding production getattr
   fallbacks to satisfy old mocks.
5. Private artifact selection and tri-state retention remain coherent. Keep is
   persisted before full-bundle resolution and survives an unsuccessful restore.
   Existing source IDs, references and immutable records are not rewritten.
6. Reference docstrings and existing Field descriptions now distinguish original
   logical addresses from current physical payload paths. Fields, defaults,
   validators and model serialization were left unchanged.
7. The revised declaration and PB06/PB07 seams distinguish durable acceptance,
   locally verified science, pending publication, verified cloud completion and
   deferred cleanup. They retain synchronous cold-read, explicit-keep and
   verified-cloud-return promises. Admitted outer ownership includes known later
   consumers and queued inputs; benchmark confirmation remains independent.

## Final assembly confirmation

The complete legacy fixture/layout successor is present under staged PB03
replace/tests/test_storage.py and has no diff against the independently reviewed
resolver author's file. Its fakes expose the actual facade contract; exact
payload verification assertions remain, while counters exclude metadata hashing
and path assertions follow the shared payload layout. The staged shared-storage
tests include the new-snapshot original-reuse check. PB04 storage.py differs
from the corrected PB03 successor only by the intended independent retention
configuration validation, so it does not overwrite the resolver corrections.

CFO-VR-05 now refers to the already declared future cleanup observation
test_stale_cleanup_preserves_replacement_and_new_keep, which checks its newer-keep
claim at the real removal boundary. That test remains planned, not authored or
executed evidence; the revision introduces no placeholder success body.

No additional ordinary production-code blocker was found in this reviewed slice.
Unknown future callers, retention timers, a second broker, durable per-read
counters, or another resolver are not requested.

## Scope limits

The native independently surviving worker, real durable admission/status,
portable proof import, source obligations, top-level owner integration and the
single destructive eligibility decision remain PB06/PB07 implementation work.
Reader primitives alone do not protect existing calls, and a proposal README
does not implement those seams. The reviewed changes must not be presented as
completed asynchronous execution or automatic offloading before their actual
implementation and required gates.
