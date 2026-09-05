# Troubleshoot VIPER

Start with the first boundary that failed. Later error messages often describe
effects of that first failure.

## Confirm the environment

```bash
source .venv/bin/activate
python -c 'import sys; print(sys.executable)'
command -v viper
```

Both executables should resolve beneath the repository's `.venv` when you are
developing this checkout.

## A plan cannot be compiled

Check these in order:

1. The project is a Git repository with a committed source state.
2. Every decorated function and project parameter model lives under the project root.
3. Every local input path exists and remains inside the project.
4. Every stage objective names a metric attached to that stage.
5. Every downstream artifact handle comes from a stage in the selected variant.

## Preflight rejects execution

Preflight validates the frozen plan against the current host. Treat a source
digest mismatch as a different plan, not as a warning to suppress. Re-author
the plan from the intended commit or restore the source it names.

## A stage failed

Use `viper status path/to/attempt.journal.jsonl` to inspect the latest durable
attempt state. Fix the project code or runtime condition, then use `viper retry`
with the same frozen plan when the intended experiment has not changed.

## Verification failed after the function returned

Check the declared artifact names and paths first. A stage can return normally
while omitting an artifact, writing outside its assigned path, or recording a
metric not attached to the stage. VIPER reports the run as successful only
after terminal verification closes these relationships.

## A CLI consumer cannot parse output

Place `--json` before the subcommand:

```bash
viper --json capabilities
```

JSON mode emits one typed success or failure document. Human mode is intended
for terminal reading.
