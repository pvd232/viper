# Source-only PB03/PB04 audit corrections

These are complete proposed successors copied from the queued action payloads.
They have not been applied to active source, imported, compiled or tested.

| PairBlock | Proposed payload | Target |
| --- | --- | --- |
| CFO-PB-03 | `CFO-PB-03/add/src/viper/_storage_locks.py` | `src/viper/_storage_locks.py` |
| CFO-PB-03 | `CFO-PB-03/add/tests/test_storage_readers.py` | `tests/test_storage_readers.py` |
| CFO-PB-04 | `CFO-PB-04/replace/src/viper/_storage_registry.py` | `src/viper/_storage_registry.py` |
| CFO-PB-04 | `CFO-PB-04/replace/src/viper/retention.py` | `src/viper/retention.py` |
| CFO-PB-04 | `CFO-PB-04/add/tests/test_artifact_retention.py` | `tests/test_artifact_retention.py` |

Corrections:

- Both queued contextmanager implementations now use the project's current
  `Generator[..., None, None]` annotation convention; the user-applied live
  lock source already has that convention. This prevents whole-file queued
  payloads from restoring the stale annotations.
- Lock documentation now states that one native owner spans every admitted
  training, inference, evaluation and diagnostics consumer. Stage/read return
  does not release its holds. The existing lifetime test now observes removal
  being blocked between two consumer reads as well as after the second read.
- Retention still uses the active workspace registry and records keep before
  ordinary materialization. Documentation and one focused wrapper test make
  the missing original-workspace case explicit without modifying references.
  The test stubs payload resolution; it does not claim portable-cloud recovery.
- The sole registry permission query is documented as a fresh decision inside
  background deletion's write transaction. Its boolean must not be captured in
  a queue request and later treated as permission to delete.

Future integration requirements remain blocking for automatic deletion:

1. PB06/PB07 must close workflow admission, join every known downstream user,
   then release the borrowed reader owner. A nested stage cannot close it.
2. Durable publication work must retain a recoverable source independently of
   reader-process lifetime. Failed/unresolved publication retains its sources.
3. Cleanup must use successful closure plus all pinned destination receipts,
   then exclusive payload protection and one short registry write transaction
   for current permissions, exact owned-file checks and conditional removal.
4. Legacy eviction and recursive removal of directories containing managed
   payloads must enter the same decision. Ordinary disposable scratch does not.
5. Portable receipt import and verified backing lookup must use the active
   workspace before touching an absent old workspace. A registry left in the
   deleted old repository is not itself portable recovery evidence.

No queue, unlink implementation, per-read subscription or unsupported durable
raw-path hold/release API was introduced here. Existing legacy eviction is
unchanged and remains outside the not-yet-connected new deletion gate.

The parent must regenerate queued payload digests, diffs and proposal manifests
after composing these successors with the resolver/publication corrections.
