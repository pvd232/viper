# Retry, restore, and compare runs

These operations start from persisted evidence. Keep the printed
`resolved.yaml` path from a successful run and the frozen plan path from a
failed run.

## Retry a failed run

```python
from viper import execution

retried = execution.retry(root, run_spec_path)
```

Retry appends a new attempt to the same frozen plan. It does not silently create
a different plan.

From the command line:

```bash
viper retry path/to/run.yaml --root .
```

## Restore verified artifacts

Restore all artifacts from one successful local run:

```bash
viper restore path/to/resolved.yaml --root .
```

Select one artifact with its `STAGE.ARTIFACT` name:

```bash
viper restore path/to/resolved.yaml \
  --root . \
  --artifacts train.model \
  --output restored/model.json
```

VIPER verifies source bytes before replacing the destination. Existing matching
bytes are reused; conflicting destination bytes are not accepted as the
recorded artifact.

## Inspect status and lineage

```bash
viper status path/to/attempt.journal.jsonl
viper lineage path/to/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/project
```

Status reads the durable attempt journal. Lineage verifies the run and returns
the stages, inputs, artifacts, and production or reuse relationships.

## Compare two runs

```bash
viper compare-runs left/resolved.yaml right/resolved.yaml \
  --left-root left-project \
  --right-root right-project \
  --trust-source https://github.com/example/project
```

Put `--json` before the command when a script or agent needs one typed result
document.
