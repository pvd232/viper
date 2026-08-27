# Contributing to VIPER

VIPER changes must preserve agreement among the public API, formal protocol,
execution evidence, verifier, and tests.

## Set up the repository

Create and activate a project-local Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable ".[test,release]"
```

On Windows, activate the environment with `.venv\Scripts\activate`.

The installation command reads VIPER and its dependencies from the current
checkout. Editable mode makes source changes available immediately. The
bracketed names add the `test` and `release` dependency groups declared in
`pyproject.toml`.

Confirm that Python resolves from `.venv` before running project commands:

```bash
python -c 'import sys; print(sys.executable)'
```

## Make a change

Keep each public type or operation in the module that owns its domain. Add a
docstring to every module, class, function, method, and test. Use inline comments
to explain a non-obvious invariant, state transition, join, or safety boundary.

Protocol changes require synchronized updates to the formal protocol,
implementation, verifier rule, and acceptance test.

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
hardware gates described in the [testing guide](docs/development/testing.md).
