# Configuration and schemas

VIPER combines a project root with explicit plan records. Most execution
settings belong to the plan rather than ambient process state.

## Project root

A VIPER project contains `viper.toml`. Commands accept `--root`; Python APIs
accept a `Path`. Root discovery prevents inputs, artifacts, and protocol files
from silently resolving against an unrelated working directory.

## Local environment

`LocalEnvSpec` records a Git-identified lockfile, observed Python environment,
and CPU compute by default. The CPU quickstart constructs it from the current
repository and `observe_python_env()`.

## Reproducibility

`ReproducibilitySpec` records deterministic algorithm settings, precision,
parallelism, and NumPy generator families. These are requested execution
controls and observations, not a universal proof of bitwise determinism across
all hardware and third-party libraries.

## Storage

Local storage is the default. Storage settings choose where immutable evidence
is published; restore and verification consume the recorded references rather
than guessing from a path convention.

## Discover schemas

List installed capabilities:

```bash
viper --json capabilities
```

Return one public JSON Schema:

```bash
viper --json schema RunSpec
```

Use the [formal protocol](protocol.md) to understand record relationships and
the command output to inspect the exact schema installed in the current
environment.
