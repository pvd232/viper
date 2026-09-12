# Contributing to VIPER

VIPER changes must preserve agreement among the public API, formal protocol,
execution evidence, verifier, and tests.

## Set up the repository

Create and activate a project-local Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable ".[test,release,mcp]"
```

On Windows, activate the environment with `.venv\Scripts\activate`.

The installation command reads VIPER and its dependencies from the current
checkout. Editable mode makes source changes available immediately. The
bracketed names add the `test`, `release`, and `mcp` dependency groups declared
in `pyproject.toml`.

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

### Review a framework tradeoff

Before accepting a change to VIPER's public authoring or execution behavior,
record one fixed workflow and compare the current and proposed paths. The review
must state:

- the guarantee gained and the evidence that verifies it;
- each new user action, restriction, and failure message;
- the runtime operations added to the fixed workflow;
- a focused benchmark when the change can affect model runtime;
- unsupported execution paths and the behavior selected for them; and
- whether the behavior is required, enabled by default, or opt-in.

When a change relies on a runtime observation hook, distinguish cooperative
evidence from a security boundary. State which operations the hook sees, which
runtime-owned operations it excludes, and how callers test native-library
behavior.

Keep the implementation in one reviewable commit with its observing tests and
documentation. Record broader release tests separately when the changed path
ends before the release boundary.

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

The [testing guide](https://github.com/pvd232/viper/blob/main/docs/development/testing.md) defines each test tier, domain
marker, CI job, and live CUDA gate.

## Submit the change

Open a pull request from a focused branch. Describe the contract or behavior
that changed and include the exact validation results. A release commit must
pass the built-distribution, clean-installation, generated-project, and live
hardware gates described in the [testing guide](https://github.com/pvd232/viper/blob/main/docs/development/testing.md).
