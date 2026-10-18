# RGP-PB-05: Keep graph copies within their resource limits

Context: the complete file list provides a size estimate before artifact downloads. Each copy needs enough room for its source files and destination checks, and must preserve original files during cleanup.

## Implementation

`TransferSpace` checks the working-directory, cache, and free-disk budgets before a snapshot is read. The promoter publishes dependencies first, uses file paths for payloads, and clears its own verified downloads after the journal confirms the destination. Original local files and shared caches remain intact.

`RunFetcher` accepts a task-owned cache directory. The Hugging Face provider can stream file bodies into the destination check while using the SDK's shared HTTP client. Streamed reads enforce the expected size while receiving bytes and check SHA-256 before the file becomes visible. Normal readers retain their existing cache behavior.

The dedicated copy process uses `HF_HUB_DISABLE_XET=1`, one upload worker, serial GCS transfers, and a bounded reusable HTTP pool. These settings keep all file-transfer phases within the declared connection limit. The later process runner owns their isolated lifetime. Disk measurements count hard-linked files once and include temporary files.

The October 18 readback exposed repeated filesystem scans during cleanup. Every caller checks usage before releasing downloads, and release only removes files. Removing its additional scan reduces the comparison from four budget checks per file to two; checks before downloads and before cleanup remain. `directory_bytes()` now uses directory-entry metadata while preserving inode deduplication and rejecting escaping symlinks. On the live cache, alternating observations measured 0.256–0.264 seconds per original scan and 0.208–0.215 seconds per revised scan. The cache was changing during these observations; they measure scan cost, not complete-transfer throughput.

The existing retention test now unpacks the publisher's `(snapshot, files)` return value correctly. Its two cases and the full repository type check pass.

## Checks

66 focused cases passed in 20.19 seconds. Pyright, docstring checks, formatting and lint checks passed. Tests include a complete mixed-cloud graph under a working-space budget, interruption after a committed upload, source preservation, oversized requests, altered streamed bodies, and shared-cache cleanup rejection. Exact commands and source hashes are in [review-checks.json](review-checks.json).

The scan repair passes full-project Pyrefly and Ruff, 53 selected provider and execution cases, and the fast gate's 597 tests and 11 subtests. Eight focused capacity, symlink, graph-copy, and recovery cases also pass at the real VM target paths with focused Pyrefly and Ruff. The added cases cover hard links, internal aliases, directory loops, dangling links, and outside file/directory/missing targets. The changed boundary is filesystem accounting and cleanup; process launch, model execution, reference rewriting, and byte verification are unchanged. Hosted integration checks cover the final branch head.

The new resource model carries three limits. The new working-space owner handles reservations and cleanup. Existing readers, providers, file identities, publication code, and journals retain their responsibilities.

## Review

Source changes are in the Git commit and pull-request diff. Independent review is pending. Application data, default storage settings, and existing SOTA pointers stay unchanged. Real-file resource measurements belong to the upcoming rehearsal and model publication.
