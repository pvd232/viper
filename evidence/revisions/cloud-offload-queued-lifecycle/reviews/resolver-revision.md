# PB03 resolver revision

Prepared files only. No active source, tests, or plan files were edited. No
imports, application commands, tests, gates, type checker, or formatter ran.

## Complete successors

| File | Prepared destination |
| --- | --- |
| `storage.py` | `CFO-PB-03/replace/src/viper/storage.py` |
| `_source.py` | `CFO-PB-03/replace/src/viper/_source.py` |
| `test_shared_storage.py` | `CFO-PB-03/add/tests/test_shared_storage.py` |

The original proposal files remain untouched. These successors preserve the
guided `member` loop naming that avoids shadowing the imported `source_file`.
The registry and lock modules remain unchanged, including their existing
`Generator[..., None, None]` annotation convention.

## Minimal changes

- `RunFetcher` passes its existing provider lookup lazily through the existing
  `cloud` injection argument. Registered original, cache, and inventory hits
  need no cloud client or cloud credentials.
- After first admitting a snapshot inventory, storage reloads its authoritative
  shared aliases so equal-content originals from other snapshots are immediately
  available; the first access does not redownload the payload.
- `LocalArtifactStore` remains the ordinary resolution owner. Snapshot member
  listing now uses its same immutable inventory lookup, so resident bundles do
  not require a cloud client merely to establish complete membership.
- A fresh fetcher first checks the current registry for a foreign local
  reference. A valid current binding works even when the old absolute
  `workspace` is absent. Only a genuinely absent current registration permits
  the old workspace fallback. Registry corruption is propagated.
- Managed Hugging Face payload downloads enable the existing streaming branch
  at the shared payload transfer boundary. The provider constructor default is
  unchanged; metadata retrieval and provider pooling remain intact. Explicit
  bounded transfer caches retain their task roots and independent downloads.
- Per-execution verification memos remain per fetcher. There is no inferred
  process lifetime, global session singleton, or new per-read user interface.

## Focused observations authored, not executed

All additions extend the existing `tests/test_shared_storage.py` owner:

1. `test_fresh_fetcher_reuses_registered_original_without_cloud_client`
2. `test_fetcher_uses_active_registry_for_foreign_local_reference`
3. `test_fetcher_propagates_invalid_active_registry_before_legacy_fallback`
4. `test_managed_huggingface_restore_streams_into_shared_store`
5. `test_bounded_huggingface_restore_keeps_task_cache`
6. `test_registered_cache_hit_does_not_construct_cloud_provider`
7. `test_new_snapshot_uses_registered_equal_content_original_without_downloading`

The HF observations use the real provider's size/hash verification and
streaming installation with mocked HTTP. Its Hub download helper permits
manifest metadata but rejects payload use, so a second checkpoint payload
cache would fail the observation.

## Mandatory remaining boundary

PB06 must supply a real outer workflow owner and acquire its borrowed reader
hold before physical resolution or memoized-path access. That owner must span
all registered downstream execution, evaluation, and benchmark calls; their
individual returns must not close it. No dormant reader parameters were added
here because no such owner exists yet.

Cold restoration through an original local reference remains pending the
verified-backing lookup in PB06. Missing local bytes fail honestly. This packet
enables no automatic deletion.
