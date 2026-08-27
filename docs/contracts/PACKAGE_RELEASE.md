# Package release

## Status

VIPER 0.1.0a1 is implemented. Its release report preserves the completed local,
distribution, installed-wheel, generated-project, Python 3.11–3.14, live GCE,
TestPyPI, and PyPI evidence.

The 0.1.0a2 revision is approved for implementation. It moves the distribution
into a clean public repository, assigns every public entity to one module,
removes superseded modules, replaces the example and documentation surfaces,
and repeats the complete publication gate.

## Required claim

Installing `viper-provenance==0.1.0a2` provides the documented Python API and
CLI from the public `pvd232/viper` repository. A user can create or open a
project, execute a decorated stage through ordinary Python, execute the same
frozen plan through the installed command, and receive equivalent verified
results outside the source checkout.

## Release result

The [release report](../releases/0.1.0a1.md) records the source commit, signed
tag, distribution digests, CI runs, registry checks, and live GCE result. Clean
environments installed the indexed wheel from both package registries and
completed the generated acquisition, five-stage candidate, benchmark
confirmation, and terminal verification.

## Public surface

Release freezes the import names listed in the API reference, the CLI commands,
JSON result schemas, stable error codes, and capability-discovery output. Every
documented name must exist in the installed wheel.

The public project interface includes the stage decorators, HTTP transport
decorator, typed contexts, and `viper.run(stage_callable)`. The CLI delegates
execution to the same application coordinator.

### Module ownership

Each public entity has one defining module. Moving an entity requires updating
its definition and every import in the same release. The release deletes the
source module after its final entity moves.

| Module beneath `viper` | Owned public surface |
|---|---|
| `parameters` | Parameter extension categories |
| `stages` | Stage specifications, decorators, contexts, and invocation receipts |
| `experiments` | Factors, levels, variants, replicates, and experiment specifications |
| `runs` | Run plans, attempts, attempt references, and resolved runs |
| `artifacts` | Artifact declarations, resolved artifacts, pointers, and loader identities |
| `references` | Hash-bound references to separately stored values |
| `metrics` | Metric interfaces, specifications, measurements, dependencies, and verification receipts |
| `benchmark` | Benchmark specifications, execution, comparisons, and results |
| `http` | HTTP requests, transports, retrievals, contexts, and receipts |
| `runtime` | Environment, reproducibility, startup, and execution-context contracts |
| `resume` | Random-generator, data-loader, and resume-state contracts |
| `execution` | Public run, retry, and benchmark orchestration |
| `verification` | Public run, artifact, pointer, and benchmark verification |
| `serialization` | Canonical YAML and JSON encoding and parsing |
| `storage` | Storage retrieval, immutable publication, and local storage |
| `api` | Typed application requests, results, dispatch, schemas, and capabilities |

`viper._schema` owns the shared Pydantic base and internal validators.
`viper._workers` owns child-process entrypoints. Names beginning with an
underscore remain outside the public API.

The refactor removes `viper.protocol`, `viper.runner`, `viper.verifier`, and
`viper.application`. Their entities and operations move to the owner modules
listed above. Serialized YAML and JSON field names, discriminators, and values
remain unchanged.

### Root imports

The package root exposes the ordinary project interface:

```python
import viper


class TrainParameters(viper.parameters.Train):
    epochs: int
    learning_rate: float


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    ...


viper.run(train)
```

The root owns stage decorators, HTTP transport decoration, typed runtime
contexts, `run`, and `retry`. Concrete protocol documents and administrative
operations are imported from their defining modules.

### Public repository

The public repository contains the installable source, tests, package
configuration, GitHub workflows, license, documentation, and one runnable
synthetic example. Its package source uses the `src/viper/` layout.

The repository excludes historical material, journals, source notes, editor
state, generated package metadata, and one-time maintenance programs. Release
and contract checks execute from tests or CI so their ownership remains next
to the gate they enforce.

## Project scaffold

`viper init PATH --package PROJECT_PACKAGE` creates a small runnable project:

```text
PATH/
├── pyproject.toml
├── experiments/
├── benchmarks/
├── src/<project_package>/
│   ├── stages/
│   ├── metrics/
│   └── artifact_loaders/
└── tests/
```

The generated layout is an example. VIPER accepts every project implementation
through repository-relative paths stored in its specs. The protocol remains
source-layout agnostic.

The generated implementation files must freeze, preflight, execute, and verify
in their generated form. The acceptance driver initializes Git before it
authors the source-bound experiment, benchmark, stage, and run documents.

The runnable example has two plans. The acquisition plan publishes the fixed
evaluation dataset and split, then writes their promoted artifact pointers.
The candidate plan contains the ordered `download`, `build`, `embed`, `train`,
and `evaluate` stages. Its evaluation stage selects the promoted evaluation
inputs and the parameters produced by its training stage. The benchmark
executes one independent confirmation of the candidate plan.

This sequence preserves the data-use contract. The training stages consume
training-role inputs. The evaluation stage receives the evaluation and
benchmark inputs published by the acquisition plan.

`PATH` must be absent or empty. The command validates every requested path and
package name before writing the first file. An occupied path returns a typed
conflict failure and preserves its contents.

## Distribution gate

The release candidate must satisfy each check:

| Check | Required result |
|---|---|
| Public imports | Every name in `docs/reference/api.md` imports from the installed wheel, and each name has one defining module. |
| Inline types | The installed `viper` package contains `py.typed`, and type checkers use its distributed annotations. |
| CLI | Every command returns documented human output, JSON, and exit status. |
| Python execution | The generated project's decorated stage executes through `python train.py` and returns a verified result. |
| Metadata | License, authors, URLs, classifiers, and version are complete. |
| Builds | Source distribution and wheel build while generated metadata remains untracked. |
| Wheel acceptance | The generated project passes the complete local acceptance path in a clean environment. |
| Cloud acceptance | The installed wheel passes the advertised live GCE smoke profile. |
| TestPyPI | The candidate installs from TestPyPI and repeats the wheel acceptance path. |
| CI | The exact release commit passes every supported Python version. |
| Release | The signed tag verifies against the release owner identity, and the PyPI files match the validated distributions. |

The CI fast job runs lint, formatting, type checking, unit tests, and contract
tests under Python 3.14. Its success starts the integration, release-candidate,
and compatibility jobs. Python 3.14 runs every host-independent test. Python
3.11–3.13 run the unit and contract tiers, build both distributions, and import
the installed wheel.

The Python Packaging User Guide defines the package metadata fields and
recommends SPDX license expressions with distributed license files:
[Writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
Its publication guide recommends PyPI Trusted Publishing because each upload
uses a short-lived, project-scoped credential:
[Publishing with GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## Propagation

| Surface | Required change |
|---|---|
| Metadata | Record the approved license, authors, `pvd232/viper` project URLs, classifiers, and `0.1.0a2` version. |
| Public API | Freeze imports, result schemas, errors, exit statuses, and capability discovery. |
| Inline types | Package `viper/py.typed` and verify it from the installed wheel. |
| Python execution | Export stage decorators, typed contexts, and `viper.run(stage_callable)`. |
| CLI | Implement `viper init` and route every command through the application API. |
| Template | Add one maintained runnable project template. |
| CI | Build, install, and exercise the wheel from outside the checkout. |
| Release | Push the signed version tag, publish its files to TestPyPI, validate those indexed files, approve the protected `pypi` environment, and publish the same files to PyPI. |

Tag signing is an owner-supplied release prerequisite. The release report
records the signing identity and the successful signature-verification command.

## Acceptance case

A clean environment installs the candidate wheel. The command
`viper init tiny-project --package tiny_project` creates the example. The
example executes its acquisition plan and promotes the evaluation inputs. It
then freezes and preflights the candidate plan. `python train.py` executes its
decorated stage through `viper.run(stage_callable)`. `viper run` executes the
complete candidate plan through the same coordinator and emits valid JSON. The
benchmark confirmation passes. The same wheel completes the live GCE smoke
case.

Deleting one documented public import causes the installed-wheel test to fail.

## Implementation order

1. Freeze module ownership and the root import surface.
2. Create the clean `pvd232/viper` repository with the approved public files.
3. Move protocol entities into their defining modules and delete
   `viper.protocol`.
4. Move orchestration and verification into their defining modules and delete
   `viper.runner`, `viper.verifier`, and `viper.application`.
5. Remove dead code and exact-operation duplicates found while consolidating
   the application surface.
6. Replace the examples with one generated synthetic project.
7. Rewrite the public documentation after the imports stabilize.
8. Set version `0.1.0a2`, build both distributions, and run the complete local,
   installed-wheel, CI, and supported-Python gates.
9. Install the exact wheel on the designated L4 host and run the generated
   project through terminal verification.
10. Publish the same validated files to TestPyPI and PyPI through Trusted
    Publishing, then repeat the clean-install acceptance case.
