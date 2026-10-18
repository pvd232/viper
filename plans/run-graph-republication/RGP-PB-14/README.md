# RGP-PB-14: Reuse verification within benchmark execution

Requirement: RGP-REQ-16. Dependency: RGP-PB-13. Repository: VIPER.
The dependency orders the PR stack; the metric and benchmark changes have no cache-format dependency.

Reuse the candidate and confirmation-stage verification completed within the same benchmark invocation and verification policy. Keep independent confirmation execution and all cross-execution lineage, parity, metric, and status checks. Independently supplied benchmark results still receive full public verification. Share metric criteria and status calculation without changing serialized records or adding durable caches.

Targets: [_benchmark.py](../../../src/viper/execution/_benchmark.py), [verification.py](../../../src/viper/verification.py), [metrics.py](../../../src/viper/_verification/metrics.py), [test_benchmark_execution.py](../../../tests/test_benchmark_execution.py). Typed verifier RGP-VR-16 names the observing tests.
After target-path import fixes and formatting, run Pyrefly on `src/viper tests`,
the affected tests, then documentation lint, format check, and lint on those roots.
Keep measured operations separate from estimates of production runtime.

Validation: passed; [tests, Pyrefly and lint](../../../evidence/rgp-pb14-validation.json). PR not created.
See the [contract status](../../../contracts/run-graph-republication.md#pr-review-and-integration).
