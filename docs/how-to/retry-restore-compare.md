# Retry, restore, and compare runs

These operations start from persisted evidence. Keep the printed `resolved.yaml` path
from a successful run and the frozen plan path from a failed run.

## Retry a failed run

```python
from viper import execution

retried = execution.retry(root, run_spec_path)
```

Retry appends a new attempt to the same frozen plan and preserves the earlier attempt
records.

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

VIPER verifies all selected source files and checks the destinations before writing. It
creates missing files, reuses matching files, and rejects an existing destination
containing different bytes. Choose a new destination to keep both versions.

## Inspect status and lineage

```bash
viper status path/to/attempt.journal.jsonl
viper lineage path/to/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/workspace
```

Status reads the durable attempt journal. Lineage verifies the run and returns the
stages, inputs, artifacts, and production or reuse relationships.

## Compare two runs

```bash
viper compare-runs left/resolved.yaml right/resolved.yaml \
  --left-root left-workspace \
  --right-root right-workspace \
  --trust-source https://github.com/example/workspace
```

Put `--json` before the command when a script or agent needs one typed result document.

## Restore from Python

Use a completed run's immutable reference to restore one artifact:

```python
from viper.restoration import ArtifactRestoreSelector

restored = execution.restore(
    root,
    resolved_run.reference,
    artifacts=(ArtifactRestoreSelector(stage_id="train", artifact_name="model"),),
)
for artifact in restored.artifacts:
    for file in artifact.files:
        print(file.status, file.path)
```

Each file reports `restored` or `already_present`. A bundle reports one entry
per member. To choose another destination, pass `output=destination_path`.

## Resume training from a checkpoint

Retrying a failed run and continuing training from a saved checkpoint are
separate operations. A retry executes another attempt of the original plan.
To continue from a completed training stage, author a new stage with both
`model` and `resume_state` inputs from the same producer.

For two training stages in one run, select both output handles:

```python
checkpoint_inputs = {
    "model": training.outputs["model"],
    "resume_state": training.outputs["resume_state"],
}
```

For a completed run, select both files with `run_artifact()` and pass them under
those same input names. Include the dataset and any other inputs your function
uses in the new stage's `inputs` mapping.

Inside a PyTorch training function, restore state in this order:

```python
import torch

from viper.resume import load_resume_state, restore_resume_state

model.load_state_dict(torch.load(context.inputs["model"], weights_only=True))
resume_state = load_resume_state(context.inputs["resume_state"])
restore_resume_state(resume_state, optimizer, dataloader, context.numpy_generators)
```

This excerpt assumes you have constructed `model`, `optimizer`, and a
`StatefulDataLoader` with the same configuration as the checkpoint. Restore the
state before creating the data-loader iterator or starting another training
step. The resumed function is responsible for using the restored state and
writing a new model and resume-state pair.

`capture_resume_state()` collects the optimizer, data-loader, and random-generator
state; `save_resume_state()` writes it. These functions and the loader-configuration
checks are defined in [`viper.resume`](../../src/viper/resume.py).
