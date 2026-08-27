# Contributing to VIPER

VIPER changes must preserve agreement among the public API, formal protocol,
execution evidence, verifier, and tests.

## Set up the repository

Repository commands use the Conda environment named `mantra`:

```bash
conda activate mantra
python -m pip install -e '.[test,release]'
```

Confirm the environment before running project commands:

```bash
echo "$CONDA_DEFAULT_ENV"
python -c 'import sys; print(sys.executable)'
```

## Make a change

Keep each public type or operation in the module that owns its domain. Add a
docstring to every module, class, function, method, and test. Use inline comments
to explain a non-obvious invariant, state transition, join, or safety boundary.

Protocol changes require synchronized updates to the formal schema, relevant
contract, implementation, verifier rule, and acceptance test. Run the contract
audit before approving a cross-document change.

## Validate the change

Run the smallest test that covers the edited behavior. Run the fast gate before
committing:

```bash
make check
```

Changes to process execution, attempt handling, metrics, resume behavior, or the
CLI also require:

```bash
make check-integration
```

Release changes require the full host-independent gate:

```bash
make check-release
```

The [testing guide](docs/development/testing.md) defines each test tier, domain
marker, CI job, and live CUDA gate.

## Submit the change

Open a pull request from a focused branch. Describe the contract or behavior
that changed and include the exact validation results. A release commit must
pass the built-distribution, clean-installation, generated-project, and live
hardware gates defined by the
[package-release contract](docs/contracts/PACKAGE_RELEASE.md).
