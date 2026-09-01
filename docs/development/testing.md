# Testing VIPER

VIPER assigns every test module one cost tier and one implementation domain.
The tier selects when the test runs. The domain selects the test set affected by
one implementation area.

## Activate the environment

Create the project environment once and install the development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable ".[test,release]"
```

The final command installs the current checkout plus its optional testing and
release tools.

For later sessions, reactivate the existing environment and confirm its Python
interpreter:

```bash
source .venv/bin/activate
python -c 'import sys; print(sys.executable)'
```

The reported path must resolve beneath the repository's `.venv` directory.

## Run the validation gates

Use the fast gate while editing:

```bash
make check
```

It runs Ruff, the Ruff formatter check, Pyright, and every unit or contract
test.

Run the integration gate after changing a process boundary or durable attempt:

```bash
make check-integration
```

Run the complete host-independent suite before building a release candidate:

```bash
make check-release
```

Run the live CUDA tests on the designated GPU host:

```bash
make check-live
```

## Cost tiers

| Tier | Boundary |
| --- | --- |
| `unit` | One implementation boundary inside the current process |
| `contract` | One public or cross-document contract with bounded collaborators |
| `integration` | A child process, complete run, CLI, metric worker, resume path, or durable attempt |
| `release` | A generated project or installed distribution completing its published path |
| `live_cuda` | A real CUDA device and its persisted execution evidence |

`tests/conftest.py` assigns one cost tier and one domain to every test module.
Collection fails when either assignment is missing.

## Domain selection

Domain markers identify the implementation owner. Run one domain while editing
that subsystem:

```bash
python -m pytest tests -q -m domain_parameters
python -m pytest tests -q -m domain_verification
```

Direct file selection remains available:

```bash
python -m pytest tests/test_run_execution.py -q
```

The marker declarations in `pyproject.toml` are authoritative.

## Continuous integration

GitHub Actions starts with the fast Python 3.14 gate. A successful fast gate
starts four independent jobs:

| Job | Required evidence |
| --- | --- |
| Integration | Every integration test under Python 3.14 |
| Release candidate | Generated-project execution, distribution build, and installed-wheel smoke test under Python 3.14 |
| Compatibility | Unit and contract tests plus build and wheel checks under Python 3.11, 3.12, and 3.13 |
| Minimum Pydantic | Project-defined parameter subclasses under Pydantic 2.12.0 |

The release commit must pass every job. A live hardware report then identifies
the exact wheel installed on the designated CUDA host and records the resulting
stage evidence.

## Protocol validation

Run the protocol and validation-architecture tests after changing a serialized
schema or verifier relationship:

```bash
python -m pytest \
  tests/test_documentation.py \
  tests/test_protocol.py \
  tests/test_validation_architecture.py \
  -q
```

`test_documentation.py` compares every protocol class repeated in the formal
reference with its defining source class. It also checks type aliases, local
links, API operation names, CLI command names, release metadata, and multiline
math fences.

The same module keeps the pending implementation contracts tied to the
[master execution checklist](master-execution-checklist.md). Every contract
requirement must name its phase and observing test. The checklist must contain
one implementation task and one test gate for that requirement in the same
phase. The check also rejects missing test modules and contract edits whose
pinned digest differs from the reviewed digest in the checklist.

That is the current requirement-level check. Master Phase 0 implements the stricter
[contract traceability](contract-traceability.md)
contract:

```text
requirement ID
-> named verifier rule
-> exact implementation file and symbol
-> exact test file and test function
```

The requirement states the promised behavior. The verifier rule names the
condition VIPER checks. The implementation symbol performs that check. The test
supplies the accepted or rejected value. Each contract also carries populated
success and rejection traces so a reviewer can inspect one real value at every
step.

Each contract-gap specification also carries three Mermaid flowcharts in its
Current gap section: the inspected current DAG, the proposed-change DAG, and
the integrated DAG. One marked worked example follows Section 4. The
documentation test parses the Section 4 Python declarations and rejects a
worked example that fails to construct one of those classes or call one of
those declared operations. Mermaid rendering remains a separate visual check;
the repository renderer must produce readable light and dark previews before
review.

The current parser remains the migration oracle until the canonical
traceability graph produces the same phase and test coverage.

Planned links name exact future symbols. Implemented links must resolve in the
candidate source tree. Phase closure requires every link to use the implemented
state.

The automatic-input contract marks one complete public workflow. Documentation
tests parse that example and require every planned public constructor. They
also require at least five used fields in each project-owned parameter model
and comments beside every major authoring and execution handoff.
