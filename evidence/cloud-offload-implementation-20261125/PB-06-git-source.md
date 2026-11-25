# CFO-PB-06 source identity amendment

Parent: `59c381d`.

Independent review found a real source-identity regression in the recovery repair:
bytes from an unrelated cache entry could satisfy a stale declared SHA for a Git
commit/path. A matching content hash does not establish that Git address.

The shared source reader now requires commit/path membership before cache, memo,
path or remembered-path reuse. A small GitFileProof contains the commit and ancestor
directory objects, not file payloads. The verifier checks their Git object IDs,
the selected file's blob ID, and its existing SHA-256/size. Both Git object formats
are supported. Repository authorization remains the existing source policy.

The existing verified-file registry stores exact-coordinate proof indexes. Git
rows cannot authorize cloud-backed eviction. Proof metadata remains after payload
eviction. Ordinary source bytes share the existing managed cache.

Native workflows group verified source paths and proof metadata into auxiliary
local snapshots before collection closes. Explicit saved-run enrollment uses the
same transport, including checkpoint publication before outer workflow closure.
The existing queue and SnapshotCopy/receipt formats carry them. There is no new
public receipt field, queue or reference format. Explicit owner closure binds its
own context and restores the previous workflow.

The existing byte verifier moved into the existing cache owner. Its callers share
that implementation; domain source/configuration validators retain their original
checks and contextual errors. Ordinary user calls and scientific record bytes stay
unchanged.

Observed checks:

- 59 queue, cleanup and pure Git-proof cases passed; two further explicit-owner
  closure cases passed after the final context repair.
- 13 real source cases passed, including repeated reads without temporary writes.
- The actual plan verifier rejects both the uncached stale declaration and a
  poisoned common-cache declaration.
- The ordinary workflow transport passed empty/nonempty source cases: no foreground
  uploads; grouped background publication; offload; persistent proof metadata;
  deletion of the producer repository; known-copy binding recovery; no prefetch on
  repeated imports; and cold cloud restoration with Git forbidden.
- The real native producer restoration observer passed in 125.68 seconds after
  original repository deletion, with unchanged producer/artifact refs and no Git
  remote access.
- Reviewers 01, 02, 03 and 04 independently approved their affected slices.

Final broad and remaining integration results are recorded separately. All cloud
observations here use controlled providers. Code reduction remains unmet; the
amendment preserves a required guarantee rather than claiming contract acceptance.
