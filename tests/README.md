# VIPER provenance tests

`tests/` verifies the protocol models, cross-record provenance checks, artifact
loaders, metric implementations, and exact training resume behavior.

## Test layers

| File | Contract verified |
|---|---|
| [protocol tests](test_protocol.py) | Individual Pydantic models reject invalid fields, paths, identifiers, stage relationships, and checkpoint declarations. |
| [documentation tests](test_documentation.py) | The formal protocol, API table, links, release metadata, and example vocabulary match the package source. |
| [verifier tests](test_verification.py) | The verifier retrieves referenced bytes and enforces relationships among run plans, stages, inputs, artifacts, attempts, measurements, and benchmarks. |
| [verifier acceptance tests](test_verification_acceptance.py) | A complete synthetic provenance chain passes through the public verifier; targeted mutations prove that broken hashes, timing, snapshots, and lineage fail. |
| [authoring tests](test_authoring.py) | Canonical experiment, variant, stage, and run-plan files are written at identity-based paths, and each frozen stage reference matches the exact serialized bytes. |
| [parameter-validation tests](test_parameter_validation.py) | Project Pydantic classes are byte-bound, loaded from a top-level symbol, checked against the correct parameter category, and invoked in a dedicated worker. |
| [command tests](test_cli.py) | The installed command dispatches to the public validation surface and reports the validated protocol type. |
| [execution acceptance test](test_execution_acceptance.py) | A real stage entrypoint runs with the canonical command and every declared output file receives an exact hash and byte count. |
| [run execution test](test_run_execution.py) | A real two-stage local run freezes a project parameter model, preflights, executes, publishes, verifies, and rejects a tampered artifact. |
| [resume tests](test_resume.py) | Python, NumPy, PyTorch, optimizer, and stateful DataLoader state round-trip so resumption selects the same next batch with zero or multiple workers. |
| [artifact-validation tests](test_artifact_validation.py) | Exact loader identities, isolated loader execution, and typed loadability or semantic-validation outcomes are enforced. |
| [metric-interface tests](test_metric_interface.py) | Decorated metric functions, stateful metric classes, and live measurement handles follow the public interface. |
| [metric-provenance tests](test_metric_provenance.py) | Production and recomputation workers bind the same implementation, parameters, dependencies, and runtime evidence. |
| [shared fixtures](fixtures.py) | Independent test modules use shared builders to construct the same valid metric and resume records. |

`test_verification_acceptance.py` exercises the verifier with an in-memory document
store. `test_execution_acceptance.py` crosses the process boundary and inspects
the files produced by a real stage command.

## Verification flow

The test layers follow the same boundary as the package:

```text
record verification

Pydantic model validation
        |
        v
canonical plan authoring
        |
        v
referenced-file retrieval and hash checks
        |
        v
cross-record verifier relationships
        |
        v
complete synthetic provenance chain

stage execution

frozen stage spec
        |
        v
real stage process
        |
        v
declared output hashes
```

Runtime resumption and artifact loaders have separate tests because their
boundaries use live Python objects and materialized files. Protocol tests
exercise serialized records.

## Running the tests

From the repository root, activate the `.venv` environment created in
[`CONTRIBUTING.md`](../CONTRIBUTING.md). Use the fast development gate during
implementation:

```text
make check
```

The fast gate runs Ruff, formatting, Pyright, and every unit and contract test.
The integration gate crosses the process, runner, CLI, resume, and durable
attempt boundaries:

```text
make check-integration
```

The release gate adds the generated-project acceptance path:

```text
make check-release
```

Tests carry one cost tier and one owned-domain marker through the manifests in
[`conftest.py`](conftest.py). Pytest can select either dimension. This command
runs the parameter domain:

```text
python -m pytest tests -q -m domain_parameters
```

Direct file selection runs the requested file independently of its tier:

```text
python -m pytest tests/test_run_execution.py -q
```

## Adding coverage

Place a test beside the narrowest contract it proves. Reuse
[shared fixtures](fixtures.py) when several modules need the same valid record.
Import production classes directly from `viper`. Keep production dependencies
out of test-to-test imports. Give every test a docstring that states the
accepted behavior or rejected failure. Add the module to both classification
manifests in `conftest.py`.
