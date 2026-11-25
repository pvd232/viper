# CFO-PB-06

**Status:** planned; complete native implementation and executable PairBlockPlan not yet frozen.

**Requirements:** CFO-REQ-03, CFO-REQ-06, CFO-REQ-07, CFO-REQ-09

**Depends on:** PB04 and PB05

Context: A direct-upload primitive and separate per-call locks do not provide durable background admission or preserve local copies across related calls. Establish one explicit outer owner before authoring and queue all native publications while its admitted consumers continue.

## Owned targets

- src/viper/authoring.py::_freeze_input and freeze_run_plan
- src/viper/execution/__init__.py
- src/viper/execution/_run.py
- src/viper/execution/_batch.py
- src/viper/execution/_benchmark.py
- src/viper/execution/_attempt.py
- src/viper/execution/_stage.py::StageWorkerContext
- src/viper/execution/_metric.py::MetricWorkerContext
- src/viper/execution/_materialization.py
- src/viper/execution/_publication.py
- src/viper/execution/results.py and existing API/CLI result adapters
- src/viper/storage.py
- src/viper/_source.py
- src/viper/execution/_offload_worker.py, only if a small dedicated entry point is required

## Contribution

Begin ownership before draft freezing, pointer publication and batch scheduling. An explicitly admitted data/training/evaluation/benchmark sequence borrows one owner, including queued-but-not-started inputs and gaps between calls. Forward the owner explicitly across executor and worker boundaries; do not assume thread context propagates automatically. Preserve independent benchmark recomputation, per-execution proof reuse and batch failure aggregation. Arbitrary future library calls are not inferred; no TTL, prediction or implicit interpreter owner is introduced.

Register and retain original paths without a mandatory second payload copy, establish immutable identity and durably admit plan/pointer/stage/attempt/terminal/benchmark work before reporting acceptance. Queue publication with offload true or false. A failed admission commit is immediate; a failed worker launch after durable admission is recoverable. A cloud destination does not justify rejecting an enrolled local producer or deleting the existing reachability guard without genuine dependency enrollment.

Use the actual JEP independent-drainer and atomic-record pattern with Viper's existing provider/journal proof. Durable pending work protects sources between process exit and worker acquisition and between retries. Workers perform network transfer, remote verification, receipts and retry; the runner never joins a transfer executor on exit. No empty-current-queue shortcut may finalize an open collection.

Supply genuine original-local-ref backing lookup in the active workspace and portable receipt import. Expose publication pending/complete/failed separately from locally verified science, retaining existing cloud-return and complete-keep waits. Do not change immutable scientific records to carry mutable execution ownership or publication state.

## Observing checks

Exact symbols are declared in the contract. They remain planned, with no placeholder test bodies:

- tests/test_background_publication.py: native authoring/final records make no foreground cloud calls; admission failure; background progress and exit; failed spawn and interrupted retry; independent publication failure/status; pending-source protection.
- tests/test_offload_workflow.py: admitted data/evaluation/benchmark lifetime; queued input protection; child closure rejection; failed returned batch; managed inputs and current-root lookup.
- tests/test_offload_recovery.py: unchanged-ref restoration, durable status and preserved synchronous guarantees.

## Gate and stop condition

Freeze complete source actions from the real PB04/PB05 dependency commit, then use Pyrefly, focused CPU/mock tests, semantic documentation/schema checks and non-mutating Ruff checks. Include native process integration checks. Stop if an outer boundary is undeclared, a managed record still blocks on cloud, durable sources can disappear, or a returned cloud reference is unverified. PB06 is not execution-ready from this README alone.
