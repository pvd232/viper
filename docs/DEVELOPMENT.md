# Development environment

VIPER repository commands use the Conda environment named `mantra`.

Use the Conda environment named `mantra` for repository Python, package, test,
schema, and validation commands.

```bash
conda activate mantra
```

Confirm the environment once after activation:

```bash
echo "$CONDA_DEFAULT_ENV"
python -c 'import sys; print(sys.executable)'
```

The environment name must be `mantra`, and Python must resolve from that Conda
environment before repository Python commands run.

## Validation gates

Use the fast gate while editing:

```bash
make check
```

This gate runs Ruff, the Ruff formatter check, Pyright, and every test marked
`unit` or `contract`. The current gate contains 165 tests and completed in
41.23 seconds on the development machine on August 24, 2026.

Run the integration gate after changing process launch, the runner, the CLI,
resume behavior, metric recomputation, or durable attempts:

```bash
make check-integration
```

The current integration gate contains 54 tests and completed in 251.49 seconds
on the same machine.

Run the release gate before publishing a candidate:

```bash
make check-release
```

The release gate runs every unit, contract, integration, and release test. It
excludes tests that require the designated CUDA host. Run those tests on that
host with:

```bash
make check-live
```

The release tier contains one generated-project acceptance test. That test
completed in 144.20 seconds on the development machine.

## Test classification

Each test module has one cost tier and one owned domain in
[`tests/conftest.py`](../tests/conftest.py). The cost tier determines when the
test runs. The domain identifies the implementation area whose changes select
that test.

| Tier | Test boundary |
|---|---|
| `unit` | One implementation boundary inside the current process. |
| `contract` | One public or cross-document contract with bounded collaborators. |
| `integration` | A process, runner, CLI, metric worker, resume, or durable-attempt boundary. |
| `release` | The generated project or installed distribution completes its published path. |

The domain markers are declared in `pyproject.toml`. A focused parameter check,
for example, is:

```bash
python -m pytest tests -q -m domain_parameters
```

Direct file selection continues to work:

```bash
python -m pytest tests/test_runner_acceptance.py -q
```

Add every new test module to both manifests in `tests/conftest.py`. Collection
fails when either classification is missing.

## Continuous integration

GitHub Actions runs the fast Python 3.14 gate first. A successful fast gate
starts three independent jobs:

| Job | Coverage |
|---|---|
| Integration | Every integration test under Python 3.14. |
| Release candidate | The generated-project test, distribution build, and installed-wheel smoke test under Python 3.14. |
| Compatibility | Unit and contract tests plus distribution and wheel checks under Python 3.11, 3.12, and 3.13. |

Together, these jobs exercise every host-independent test under Python 3.14
and the public package boundary under every supported Python version. A newer
commit cancels the active run for an older commit on the same branch.
