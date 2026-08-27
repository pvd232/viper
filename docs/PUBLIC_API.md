# Public Python API

This document defines the approved VIPER 0.1 Python surface. Installed-wheel
tests exercise each path before release.

## Stability boundary

Every module, name, call signature, return value, side effect, and documented
exception in this file belongs to the public API. Names beginning with an
underscore remain internal. The [versioning policy](VERSIONING.md) governs
incompatible changes after publication.

The package includes a `py.typed` marker. Type checkers may therefore use the
inline annotations distributed with the installed `viper` package.

## Modules

| Module | Public responsibility |
| --- | --- |
| `viper.application` | Typed operations, requests, successes, failures, schema discovery, and capability discovery |
| `viper.artifacts` | Artifact declarations, resolved artifacts, pointers, and loader identities |
| `viper.authoring` | Canonical experiment, variant, benchmark, stage, and run-plan documents |
| `viper.benchmark` | Benchmark specifications, execution, comparisons, and results |
| `viper.experiments` | Factors, variants, replicates, and experiment specifications |
| `viper.http` | Built-in HTTPX retrieval, project transport decorators, and typed transport contexts |
| `viper.ids` | Validated identifier types |
| `viper.inspection` | Deterministic attempt status, plan comparison, verified-run comparison, and lineage construction |
| `viper.journal` | Synchronized attempt-state journals |
| `viper.local_store` | Immutable repository-local files and stage snapshots |
| `viper.materialization` | Verified stored-input and same-run input materialization |
| `viper.metrics` | Decorated functions, stateful metrics, comparison, and measurement output |
| `viper.parameters` | Public parameter categories for stages, metrics, and HTTP transports |
| `viper.preflight` | Complete-plan checks for the active single-host environment |
| `viper.references` | Hash-bound references to separately stored values |
| `viper.resume` | Training resume-state capture, persistence, and restoration |
| `viper.runner` | Complete trusted single-host run execution and publication |
| `viper.runs` | Run plans, attempts, attempt references, and resolved runs |
| `viper.runtime` | Environment, reproducibility, startup, and execution-context contracts |
| `viper.serialization` | Duplicate-key-safe parsing and canonical document encoding |
| `viper.stage_execution` | One controlled stage-process invocation on the active host |
| `viper.stages` | Stage decorators, typed contexts, and direct Python execution |
| `viper.verifier` | Run, benchmark, and promoted-artifact verification |
| `viper.worker` | Project command execution through the selected backend |
| `viper.workspace` | Bounded attempt directories and exclusive run ownership |

## Root package

`import viper` exposes these modules:

```python
viper.application
viper.artifacts
viper.authoring
viper.benchmark
viper.experiments
viper.http
viper.ids
viper.inspection
viper.journal
viper.local_store
viper.materialization
viper.metrics
viper.parameters
viper.preflight
viper.references
viper.resume
viper.runner
viper.runs
viper.runtime
viper.stage_execution
viper.stages
viper.worker
viper.workspace
```

The root package also exposes the project-facing stage interface:

```python
viper.download_stage
viper.build_stage
viper.embed_stage
viper.train_stage
viper.evaluate_stage
viper.http_transport
viper.StageContext
viper.DownloadContext
viper.HttpRetrievalHandle
viper.HttpTransportContext
viper.HttpTransportResult
viper.run
```

`viper.run(stage_callable)` is the ordinary Python adapter. The complete-plan
application operation remains `viper.application.run(request)`.

`viper.StageContext.numpy_generators` exposes the named NumPy generator objects
configured by the frozen run controls. The mapping keys match the names stored
in the stage invocation binding and process-startup receipts.

The release application surface also includes:

```python
viper.application.retry
viper.application.execute_benchmark
viper.application.init_project
```

Import concrete classes and functions from their owning module. For example:

```python
from viper.application import ValidateStageRequest, validate_stage
from viper.runs import RunSpec
```

## Project parameter models

`viper.parameters.ParameterModelRef` identifies one project-owned Pydantic class
by repository-relative path, top-level symbol, SHA-256 digest, and byte count.
Every `ParameterizedSpec` requires this reference. Download, build, embed,
train, and evaluate specs inherit that contract.

Projects specialize the categories exposed by `viper.parameters`:

| Category | Project extension |
| --- | --- |
| `viper.parameters.Download` | Download parameters |
| `viper.parameters.Build` | Build parameters |
| `viper.parameters.Embed` | Embedding parameters |
| `viper.parameters.Train` | Training parameters |
| `viper.parameters.Evaluate` | Evaluation parameters |
| `viper.parameters.Metric` | Metric parameters |
| `viper.parameters.HttpTransport` | HTTP transport parameters |

See [Project parameters](contracts/PARAMETERS.md) for the authoring
contract.

## HTTP transports

`viper.authoring.expand_http_url()` expands path fields and ordered query
values into the normalized URL stored by `HttpRequestSpec`.

`viper.http` exposes:

| Name | Responsibility |
| --- | --- |
| `http_transport()` | Decorate one project transport callable and bind its transport ID and parameter class. |
| `HttpTransportContext` | Deliver one frozen request, a runtime credential, a dedicated retrieval workspace, the assigned destination, the retrieval policy, validated transport parameters, and preflight-verified executable paths. |
| `HttpTransportResult` | Return the completed body path and terminal HTTP response. |
| `viper.parameters.HttpTransport` | Base class for project-defined transport parameters. |

The built-in transport ID is `httpx`. A `ProjectHttpTransportSpec` freezes a
decorated callable through its repository-relative path, symbol, SHA-256, byte
count, parameter model, complete parameter mapping, and external executable
requirements.

## Serialization compatibility

`viper.serialization.serialize_document()` is the canonical encoder.
`serialize_record()` remains available through the 0.1 release and emits a
`DeprecationWarning`.

## Repository validation interface

VIPER maintains four cost tiers for its own test suite. Each test module has
exactly one tier in `tests/conftest.py`.

| Tier | Required claim |
|---|---|
| `unit` | One implementation boundary produces the expected value or rejection. |
| `contract` | One public or cross-document contract holds across its participating components. |
| `integration` | A process, runner, CLI, metric worker, resume, or durable-attempt path completes. |
| `release` | An installed distribution or generated project completes the published user path. |

Each module also has one `domain_*` marker naming the implementation area it
exercises. The tier selects a validation budget. The domain selects tests for
one area of change.

The maintained commands are:

| Command | Coverage |
|---|---|
| `make check` | Ruff, formatting, Pyright, unit tests, and contract tests. |
| `make check-integration` | Every host-independent integration test. |
| `make check-release` | Every host-independent tier, including generated-project acceptance. |
| `make check-live` | Tests that require the designated CUDA host. |
| `python -m pytest tests -q -m domain_parameters` | Every test owned by the parameter domain. |

Collection fails when a test module lacks a tier or domain. Pytest also rejects
unknown markers and unknown configuration keys. The operational procedure and
current measured timings live in [Development environment](DEVELOPMENT.md).

The release claim requires more than a passing repository test suite. VIPER
also builds the source archive and wheel, checks both distributions, installs
the wheel outside the source checkout, exercises every supported Python
version, runs the generated project, and completes the designated CUDA-host
gate. [Package release](contracts/PACKAGE_RELEASE.md) defines that complete
sequence.

## Design basis

The public boundary follows [PEP 387](https://peps.python.org/pep-0387/), which
includes names, signatures, return values, side effects, and raised exceptions
in a Python API's compatibility surface. Inline type distribution follows
[PEP 561](https://peps.python.org/pep-0561/) through the packaged `py.typed`
marker.

The validation interface uses registered pytest markers for selective runs and
strict configuration for immediate classification errors. These mechanisms
come from pytest's [marker](https://docs.pytest.org/en/stable/example/markers.html)
and [integration-practice](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
guidance. The release gate tests the installed wheel outside the checkout,
which exercises the files users actually receive.
