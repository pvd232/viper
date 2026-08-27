# VIPER contracts

This directory owns the implementation contracts that connect one VIPER claim
to its protocol fields, runtime operation, persisted evidence, verifier rule,
and acceptance test.

## Naming

Each filename names one contract subject. The `contracts/` directory supplies
the shared document class, so filenames omit a repeated `_CONTRACT` suffix.

Each contract uses one status:

| Status | Meaning |
|---|---|
| Draft | Authoring or audit repair is in progress. |
| Audited | All five system-review gates pass; owner approval is pending. |
| Approved | The audited design is approved for implementation. |
| Implemented | Code and acceptance tests establish the required claim. |

## Contract index

| Contract | Status | Release gate |
|---|---|---|
| [Parameters](PARAMETERS.md) | Implemented | Project parameter identity and validation |
| [Stage invocation](STAGE_INVOCATION.md) | Implemented | Typed delivery of validated stage parameters and paths |
| [Process startup](PROCESS_STARTUP.md) | Implemented | Run-wide controls applied before each stage callable executes |
| [HTTP retrieval](HTTP_RETRIEVAL.md) | Implemented | Selectable transport delivery of verified retrieved files |
| [Metric provenance](METRIC_PROVENANCE.md) | Implemented | Exact metric dependencies, execution, and recomputation |
| [Artifact validation](ARTIFACT_VALIDATION.md) | Implemented | File identity, loadability, and reserved semantic validation |
| [Attempt execution](ATTEMPT_EXECUTION.md) | Implemented | Failed attempts, successive attempt IDs, and retry |
| [Benchmark execution](BENCHMARK_EXECUTION.md) | Implemented | Independent confirmation produced from a frozen run plan |
| [Cloud execution](CLOUD_EXECUTION.md) | Implemented | Execution on a pre-provisioned GCE instance |
| [Package release](PACKAGE_RELEASE.md) | Approved | Clean public repository, installed-distribution, and publication acceptance |

The [master execution checklist](../PUBLICATION_TODO.md) orders these contracts. The
[protocol](../ProvenanceS1_v3.md) remains the authority for serialized VIPER
documents.

The [contract audit](AUDIT.md) records the evidence supporting each contract's
current status.
