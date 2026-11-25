# Resolver preparation: final source review

Reviewer/author: `/root/augmentation_resolver_review`.

This report identifies the final scratch proposals supplied to the controller. It is source review and preparation only. No active repository source or tests were changed. No test, gate, formatter, type checker, or application command ran.

| Proposed file, relative to this preparation root | Prepared destination | SHA-256 |
| --- | --- | --- |
| `resolver/pb03/storage.py` | `CFO-PB-03/replace/src/viper/storage.py` | `3c7442ba21d2ecb88f6581e195a766cec7e7c647c2ee8d386b4b3b32d1388862` |
| `resolver/pb03/_source.py` | `CFO-PB-03/replace/src/viper/_source.py` | `1083fd48d2be49ca62493978863c435eae8b21aa2515d535ee10825bd807f484` |
| `resolver/pb03/test_shared_storage.py` | `CFO-PB-03/add/tests/test_shared_storage.py` | `1789fa307c50deec3fdb87263f9af0f487223ecefc96bd6dec1ee61fd6920c12` |
| `resolver/pb03/test_storage.py` | `CFO-PB-03/replace/tests/test_storage.py` | `4a8f5c40d11dbb7bd5c9feacda461de07168dbcdec8502c76ddf8b84a9524cca` |
| `resolver/pb04/storage.py` | `CFO-PB-04/replace/src/viper/storage.py` | `c0dc8b0669d2ce5c5d2cb4602f9dab47272f3b55f885f49c7b83d22777768d2b` |

## Source findings and corrections

- Current-root registry lookup precedes legacy source-workspace fallback for foreign local references. Registry corruption propagates. Missing old absolute workspace directories are not recreated when a current binding exists.
- Original and shared-cache resolution, including complete bundle-member listing, uses the same immutable inventory owner before lazily obtaining a cloud client. Per-execution verification memos remain local to each fetcher.
- Initial inventory admission reloads the authoritative shared aliases, so the first access to another snapshot can reuse a known equal-content original instead of redownloading it.
- Hugging Face payload transfers enable the existing streamed verification and atomic installation branch at the shared resolver transfer boundary. Provider constructor defaults, metadata retrieval, service pooling, and bounded task cache roots are preserved.
- Guided `member` loop names are preserved, including the existing reuse loop fix that avoids shadowing imported `source_file`. Registry/lock Generator annotations are unaffected because those modules were not modified here.

## Observations authored, not executed

The existing shared-storage module is extended with seven focused observations:

1. `test_fresh_fetcher_reuses_registered_original_without_cloud_client`
2. `test_fetcher_uses_active_registry_for_foreign_local_reference`
3. `test_fetcher_propagates_invalid_active_registry_before_legacy_fallback`
4. `test_managed_huggingface_restore_streams_into_shared_store`
5. `test_bounded_huggingface_restore_keeps_task_cache`
6. `test_registered_cache_hit_does_not_construct_cloud_provider`
7. `test_new_snapshot_uses_registered_equal_content_original_without_downloading`

Existing storage-test fixture propagation supplies the actual provider, complete inventory, and verified-path contract in three narrow cloud fakes. The service pool fixture uses a separate revision for its differently named member, keeping its complete-listing and pooling assertions truthful. Shared cache-path setup and physical payload-layout expectations follow the new ordinary storage home. Payload hash-count instrumentation excludes registry-document hashing while retaining its exact payload-count assertions. Integrity failures, corruption repair, immutable references, and byte-equality assertions remain.

## Remaining requirements

PB06 must provide actual outer workflow ownership and acquire borrowed reader holds before resolver or memoized-path physical access. The owner must span known downstream run/evaluation/benchmark consumers. No dormant reader parameters or inferred interpreter/session discovery were introduced here.

Cold restoration through original local references still requires the genuine verified-backing lookup in PB06. Missing bytes fail explicitly. These proposals activate no automatic deletion and claim no runtime acceptance.

The stale-cleanup/new-keep observation belongs to the controller's planned VR08 `test_offload_workflow::test_stale_cleanup_preserves_replacement_and_new_keep`; no duplicate or placeholder observation was added to the retention module.
