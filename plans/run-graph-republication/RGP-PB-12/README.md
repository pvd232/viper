# RGP-PB-12: Retain bounded destination downloads

Requirement: RGP-REQ-14. Dependency: RGP-PB-10. Repository: VIPER.
The dependency orders the PR stack; the metric and benchmark changes have no cache-format dependency.

Retain verified destination payloads between graph comparison and ordinary verification within one copy invocation. Reclaim only owned cache files when the next reservation exceeds a budget. Preserve independent source checks, full metadata comparison, resource failures, final cleanup, and fresh-reader byte verification.

Targets: [_promotion_transfer.py](../../../src/viper/execution/_promotion_transfer.py), [_promotion_compare.py](../../../src/viper/execution/_promotion_compare.py), [_promotion_worker.py](../../../src/viper/execution/_promotion_worker.py), [test_cloud_service.py](../../../tests/test_cloud_service.py), [test_run_execution.py](../../../tests/test_run_execution.py). Typed verifier RGP-VR-14 names the observing tests.
After target-path import fixes and formatting, run Pyrefly on `src/viper tests`,
the affected tests, then documentation lint, format check, and lint on those roots.
Keep measured operations separate from estimates of production runtime.

Validation: passed; [43 tests, Pyrefly and lint](../../../evidence/rgp-pb12-validation.json). [PR #16](https://github.com/pvd232/viper/pull/16).
See the [contract status](../../../contracts/run-graph-republication.md#pr-review-and-integration).
