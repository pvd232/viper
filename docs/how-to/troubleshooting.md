# Troubleshoot VIPER

Start with the first reported error. Later errors may result from the same missing file,
invalid declaration, or failed stage.

## Confirm the environment

```bash
source .venv/bin/activate
python -c 'import sys; print(sys.executable)'
command -v viper
```

Both executables should resolve beneath the repository's `.venv` when you are developing
this checkout.

## Plan compilation failed

Check these in order:

1. The workspace is a Git repository with a committed source state.
2. Decorated functions, loaders, and custom config classes live in importable
   Python files under the workspace root. Built-in config classes come from VIPER.
3. Every local input path exists and remains inside the workspace.
4. Every stage objective names a metric attached to that stage.
5. Every downstream artifact handle comes from a stage in the selected variant.

## Preflight rejects execution

Preflight validates the frozen plan against the current host. A source digest mismatch
means the available code differs from the selected source. Re-author the plan from the
intended commit or restore the source it names.

## A stage failed

Use `viper status path/to/attempt.journal.jsonl` to inspect the latest attempt
state. After fixing a transient runtime condition, use `viper retry` with the original
frozen plan. If you change source code, config, or inputs, commit the changes and create
a new plan. A retry checks the original source identity; incorporating a code fix
requires a new plan.

## Verification failed after the function returned

Check the declared output names and paths first. A stage can return normally while
omitting an output, writing outside its assigned path, or recording an undeclared
metric. VIPER reports the run as successful only after verification confirms the
required outputs and measurements.

## A CLI consumer fails to parse output

Place `--json` before the subcommand:

```bash
viper --json capabilities
```

JSON mode emits one typed success or failure document. Human mode is intended for
terminal reading.
