# Retry, restore, and compare runs

Keep the printed `resolved.yaml` path from a successful run and the saved
`spec.yaml` path from a failed run. Commands below use example paths; replace
them with your files. The restoration snippet uses `resolved_run`, returned by `execution.run(draft)`
in the [CPU tutorial](../tutorials/getting-started.md).

## Retry a failed run

Replace `YOUR_RUN_ID` with the failed run's ID:

```python
from viper import execution
from viper.repository import resolve_root

root = resolve_root()
plan_path = root / "experiments/cpu_quickstart/runs/baseline/YOUR_RUN_ID/spec.yaml"
retried = execution.retry(root, plan_path)
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

`status` reports progress from the attempt journal. `lineage` verifies the run
and shows which stages produced its artifacts, including any results reused
from earlier runs.

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

For two training stages in one run, start with the `training` declaration in
the [CPU quickstart](../../examples/cpu_quickstart.py) and select both output handles:

```python
checkpoint_inputs = {
    "model": training.outputs["model"],
    "resume_state": training.outputs["resume_state"],
}
```

For a completed run, select both files with `run_artifact()` and pass them under
those same input names. Include the dataset and any other inputs your function
uses in the new stage's `inputs` mapping.

This complete PyTorch example performs one update, saves a checkpoint, and
restores it into a new model, optimizer, and loader. It verifies that the next
batch and model values match. Run it in the environment where VIPER is installed:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

import torch
from torch.utils.data import TensorDataset
from torchdata.stateful_dataloader import StatefulDataLoader

from viper.resume import (
    capture_resume_state, load_resume_state, restore_resume_state, save_resume_state,
)


def make_loader() -> StatefulDataLoader:
    return StatefulDataLoader(
        TensorDataset(torch.arange(6, dtype=torch.float32).reshape(-1, 1)),
        batch_size=2,
        shuffle=False,
        num_workers=0,
    )


torch.manual_seed(7)
model = torch.nn.Linear(1, 1)
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loader = make_loader()
iterator = iter(loader)
values = next(iterator)[0]
optimizer.zero_grad()
loss = torch.nn.functional.mse_loss(model(values), 2 * values)
loss.backward()
optimizer.step()

with TemporaryDirectory() as directory:
    model_path = Path(directory) / "model.pt"
    state_path = Path(directory) / "resume_state.pt"
    torch.save(model.state_dict(), model_path)
    save_resume_state(
        state_path,
        capture_resume_state(optimizer, loader, {}, capture_legacy_global=True),
    )
    expected_batch = next(iterator)[0]

    resumed_model = torch.nn.Linear(1, 1)
    resumed_optimizer = torch.optim.Adam(resumed_model.parameters(), lr=0.01)
    resumed_loader = make_loader()
    resumed_model.load_state_dict(torch.load(model_path, weights_only=True))
    restore_resume_state(
        load_resume_state(state_path), resumed_optimizer, resumed_loader, {},
    )
    actual_batch = next(iter(resumed_loader))[0]
    assert torch.equal(actual_batch, expected_batch)
    assert torch.equal(resumed_model(actual_batch), model(expected_batch))
    print("Restored model and next batch match.")
```

Within a VIPER stage, write the checkpoint to `context.outputs["model"]` and
`context.outputs["resume_state"]`; a resumed stage reads the corresponding
`context.inputs` paths. Pass `context.numpy_generators` to capture and restore
when the plan declares named NumPy generators. Construct the matching model,
optimizer, and loader before restoring, and restore before creating the next
loader iterator. This example uses PyTorch state dictionaries; the introductory
CPU model uses its own JSON representation.

The loader-configuration checks are defined in
[`viper.resume`](../../src/viper/resume.py).
