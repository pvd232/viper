# Testing VIPER

VIPER assigns every test module one cost tier and one implementation domain.
The tier selects when the test runs. The domain selects the test set affected by
one implementation area.

## Activate the environment

```bash
conda activate mantra
echo "$CONDA_DEFAULT_ENV"
python -c 'import sys; print(sys.executable)'
```

The environment name must be `mantra`, and the interpreter must resolve from
that environment.

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
starts three independent jobs:

| Job | Required evidence |
| --- | --- |
| Integration | Every integration test under Python 3.14 |
| Release candidate | Generated-project execution, distribution build, and installed-wheel smoke test under Python 3.14 |
| Compatibility | Unit and contract tests plus build and wheel checks under Python 3.11, 3.12, and 3.13 |

The release commit must pass every job. A live hardware report then identifies
the exact wheel installed on the designated CUDA host and records the resulting
stage evidence.

## Contract audit

The specification audit compares repeated protocol classes, compiles proposed
model snippets, checks value lifecycles, and traces named verifier requirements
into acceptance tests. Run its tests after changing a contract or protocol
document:

```bash
python -m pytest tests/test_contract_audit.py -q
```

The audit supports technical review. Approval still requires examining each
claim-bearing value from its producer through its persisted representation and
verifier reconstruction.
