# RGP-PB-13: Stream metric dependency hashing

Requirement: RGP-REQ-15. Dependency: RGP-PB-12. Repository: VIPER.
The dependency orders the PR stack; the metric and benchmark changes have no cache-format dependency.

Hash metric dependency files with bounded memory in the worker. Preserve ordered SHA-256 and byte counts, changed-byte rejection before invoking the metric, and missing, empty, or symbolic-link rejection. Each worker independently checks its actual input bytes.

Targets: [metrics.py](../../../src/viper/_workers/metrics.py), [test_metric_provenance.py](../../../tests/test_metric_provenance.py). Typed verifier RGP-VR-15 names the observing tests.
After target-path import fixes and formatting, run Pyrefly on `src/viper tests`,
the affected tests, then documentation lint, format check, and lint on those roots.
Keep measured operations separate from estimates of production runtime.

Validation: passed; [19 tests, Pyrefly, lint and memory measurement](../../../evidence/rgp-pb13-validation.json). [PR #17](https://github.com/pvd232/viper/pull/17).
See the [contract status](../../../contracts/run-graph-republication.md#pr-review-and-integration).
