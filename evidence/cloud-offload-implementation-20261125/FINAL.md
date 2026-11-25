# Final implementation and validation

Runtime source: `df10a3e2258a28d7eb276d5a35a5621c0384a694`.
JEP integration: `d44073e296a638944a83684e9635d9b7fffc104f`, which pins that Viper commit.

Published review branches:

- [Viper PR 24](https://github.com/pvd232/viper/pull/24), against main at `f659faf7e7d0b721af736520c1b2b201d778c891`.
- [JEP PR 26](https://github.com/pvd232/JEP/pull/26), against feature/jep-viper-publication-adapter-20261120 at `c2f9716e398dd5442ca9d3579dfa788657a6cd00`.

## Observed checks

- `make check`: Ruff and formatting pass, Pyrefly zero errors, 805 tests and 11 subtests pass, four skips. Runtime: 499.66 seconds. [Raw log](validation/make-check.log).
- All 227 selected integration nodes have successful observations across bounded runs, including 71 native and 27 README nodes. The exact union, retained logs and historical-prefix provenance are in [the integration audit](../cloud-offload-integration-20261125/coverage.json).
- JEP final-pin suite: 47 tests and four subtests pass in 2.80 seconds; focused Pyrefly zero errors. [CPU log](validation/jep-tests.log) and [type-check log](validation/jep-pyrefly.log).
- Ten independent agent reviews were reconciled, including source-identity, reader/cleanup ordering and current-generation recovery amendments. [Review record](reviews.md).
- MAO accepted the handoff in the requested orchestrator conversation; the fresh native turn was running at observation. [Delivery record](handoff-delivery.json).

README program timeouts cover aggregate multi-run execution and independent verification. Retained stack samples and attempt progress explain cold interpreter/loader startup. Individual 120-second child/worker limits and all numerical, replay and tamper assertions remain. The final test-comment correction changes no executable AST.

## Acceptance boundary

The user accepted the measured size increase on 2026-11-25; [the owner exception](../revisions/cloud-offload-size-override-20261125.json) removes net reduction as a release gate. The physical count is unchanged: maintained runtime grows by 4,986 lines and tests by 5,777, total 10,763 across both repositories. Retired planning copies receive no reduction credit. [Exact count evidence](review-10/README.md).

At the implementation handoff the PRs were drafts and no main-branch merge or package release had occurred. The owner has since authorized the 0.3.0 publication. The production contract parser is unavailable; static TOML/AST binding checks are separate from formal protocol acceptance. Cloud transfers were controlled tests; no live cloud roundtrip, infrastructure change or annotation campaign was performed by this implementation task. All seven GitHub CI jobs passed at runtime commit `df10a3e`, including fast, integration, Python 3.11–3.13 compatibility, minimum-Pydantic and release-candidate validation; see [the CI snapshot](validation/github-ci.json).

All seven CI jobs also passed at published evidence head `33d9321`, including the final test-comment clarification. [Evidence-head CI snapshot](validation/github-ci-evidence-head.json).

## Package publication

Viper PR 24 is merged. [Viper 0.3.0](https://pypi.org/project/viper-provenance/0.3.0/)
is published from signed tag `v0.3.0` at
`96d83b86314969e166023c2a87f127f716454139`. Runtime files are unchanged from
`df10a3e2258a28d7eb276d5a35a5621c0384a694`; JEP remains a separate repository
and is not packaged or required by Viper.

The [publication receipt](../../docs/releases/receipts/0.3.0.json) records the
successful release workflow and exact file hashes, installation checks and
verified publisher attestations. A temporary L4 worker passed seven live CUDA
tests and nine autocast regressions against that CI wheel; its instance and
boot disk were deleted. The existing JEP workers were not started or changed.
The previously delivered MAO handoff remains recorded above.
