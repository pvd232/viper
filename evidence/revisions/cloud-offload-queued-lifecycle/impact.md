# Accepted Queued Lifecycle Revision

The user accepted the source-backed advice and requested the contract and queued code be updated. This report retains that accepted analysis. It records source inspection and proposed behavior, not executed application evidence.

## Fixed scenario

Use the existing `examples/evaluation.py`: one ordinary run produces held-out data, another trains/evaluates against exact prior-run artifacts, and `execution.benchmark()` independently confirms the candidate. Preserve the same inputs, scientific outputs, reference identities, and independent benchmark computation. The decision under review is when storage work runs and how long known local consumers protect resident bytes.

## Current

- `authoring.py:1706` freezes a plan locally and, with a cloud destination, synchronously publishes its compiled files at 1733. `_freeze_input():968` also publishes pointers and rejects local producer references for a cloud-destined graph at 995.
- `execution/_attempt.py:695` publishes a stage before its after-stage metrics at 718; terminal publication at 830 precedes `RunResult` at 847.
- `execution/_attempt.py:252`, `_benchmark.py:124` create separate fetchers. `_source.py:215` remembers original paths only in that fetcher; its cloud path branch at 199 checks a separate verified cache and may download despite a resident original from an earlier execution.
- The prepared PB03 resolver already centralizes local aliases, but its fetcher eagerly creates the provider before that lookup. Ordinary HF restoration also defaults to Hub download then copy, creating a second persistent payload copy.
- `execution/_batch.py:54` owns a submitted batch, not a producer-to-future-benchmark scheduler. `inputs.py:108` describes FutureInputRef only within a run. Separate later library calls are not automatically one admitted workflow.
- `retention.py:96` is explicit legacy eviction. It verifies then unlinks/rmtree at 216; it does not yet consume the proposed registry/reader/cleanup predicate. Native durable admission and automatic cleanup remain unimplemented.

## Proposed

One explicit top-level driver admits the complete data/training/evaluation/diagnostics/benchmark sequence before child completion can close it. Child calls and managed workers borrow this owner. Protect queued inputs before their execution and preserve local availability through gaps between calls. Independent later calls require their own admitted boundary or an existing keep preference, rather than prediction, timeouts or process-global ownership.

Finish writes, establish identity and durably register original locations and publication work before reporting acceptance. A failed admission commit is immediate. Native authoring and execution queue all publication records with offload either enabled or disabled. An independently surviving worker performs transfers, full verification, final receipt work and retry. Pending publication retains required sources between worker attempts and process exit.

The shared resolver chooses a verified registered original before a shared store payload and downloads only genuinely missing bytes. Provider creation is lazy. Managed HF payload downloads reuse the existing streaming branch into Viper's same-filesystem staging and shared store; provider metadata and bounded task staging retain their owners.

Successful joined outer closure queues cleanup and returns without awaiting cloud work. The worker rechecks real closed-root success, all-target final proof, source obligations, current subscriber policy, reader exclusion and exact owned binding immediately before removal. A queued request is not permission to unlink. Keep/busy/pending conditions defer cleanup without blocking ready uploads. Later cleanup reuses committed proof.

## Integrated owner and propagation map

| Responsibility | Existing seam | Accepted change owner |
| --- | --- | --- |
| Original-first current-root resolution | LocalArtifactStore, RunFetcher, VerifiedObjectCache | PB03, completed backing connector in PB06 |
| Immutable inventory and current custody | StorageRegistry and existing inventory validator | PB02; preserve one authority |
| Retention and complete-bundle keep | retention setter and registry derived subscriber query | PB04; preserve synchronous complete keep |
| Exact original publication and committed proof | PublicationJournal, providers | PB05 worker primitive; no second queue/status authority |
| Root admission and local source obligations | Public run before authoring, batch before scheduling, benchmark through final publication | PB06 |
| Independent process and durable progress/status | Existing JEP admission/drainer pattern plus Viper journal | PB06; actual native integration still missing |
| Deferred final removal | Existing legacy retention and reader locks | PB07, same native work mechanism and one live decision |
| JEP driver lifecycle and duplicate removal | JEP's existing top-level driver | PB09 after native acceptance |

## Guarantees and friction

- Immutable reference formats, original membership, hashes, run bytes, and completed publication receipts remain unchanged. Pending publication is visible separately from scientific success.
- Existing verified-cloud-return APIs continue waiting for their promised result. A cold path read needs usable verified bytes before computation. Explicit keep still waits for complete local availability. These are deliberate completion boundaries rather than hidden cloud synchronization in ordinary queued execution.
- Local hashing, source durability and admission commits still do real local work. Queueing cannot report persistence that failed or make a needed absent payload usable before arrival.
- Full remote byte verification can read remote payload bytes. Preserve that guarantee and its proof; do not claim background work removes bandwidth or replace it silently with metadata-only checks.
- Shared storage does not bypass scientific verification or independent benchmark computation. Batch-returned failures count as workflow failure even when no exception escapes the body.
- The source host/disk remains required until verification or verified durable handoff. The worker must not be a caller-owned executor joined on scope exit.

## Evidence disposition

The initial identity requirement/verifier/PairBlock remain unchanged. This revision strengthens locality, ownership, queued publication, cleanup and completion claims, so affected future checks must be rerun when implemented. Source review does not preserve or fabricate any implementation gate or acceptance. The production declaration-impact plan and metadata validation are retained separately. Application checks remain user-deferred.
