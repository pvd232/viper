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

Every external action is pinned to a full commit SHA. The adjacent comment
records the corresponding release line. GitHub identifies a full commit SHA as
the immutable action reference in its [secure-use
guidance](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions).

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
  tests/test_workflow_documentation.py \
  tests/test_protocol.py \
  tests/test_validation_architecture.py \
  -q
```

`test_documentation.py` compares every protocol class repeated in the formal
reference with its defining source class. It also checks type aliases, local
links, API operation names, CLI command names, release metadata, and multiline
math fences.

The active [0.1.0a3 core release contract](v0.1.0a3-core-release.md) owns the
cleanup inventory and release acceptance boundary. Git history and its named
preservation branch retain the retired planning, traceability, source-impact,
and research documents.

## macOS child-process launching

Production code imports the private `viper._subprocess` facade. On macOS, the
facade starts a Python bridge through `posix_spawn`; the bridge applies the
requested process settings and replaces itself with the target executable.

`tests/test_process_startup.py` disables `_fork_exec` while running a real
command, verifies its output, and checks the previously crashing preflight Git
read. It replaces `platform.processor()` with a rejecting stub while observing
the local runtime, because that standard-library helper starts an unguarded
subprocess on macOS. It also scans `src/viper` and `tests` and rejects direct
standard-library subprocess imports outside the facade and that regression
module. Run it without `OBJC_DISABLE_INITIALIZE_FORK_SAFETY` after changing a
repository-owned process boundary.
