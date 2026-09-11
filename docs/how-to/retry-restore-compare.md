# Retry, restore, and compare runs

Use saved run files for the operations below. The
[inspection tutorial](../tutorials/inspect-results.md) also shows them together
in one complete program.

## Retry a failed run

Run [the recovery example](../../examples/recovery.py) with
`python -m examples.recovery`. It deliberately fails its first training attempt,
retries the same plan, indexes the successful result, and reuses it in a new run.
The training function computes the model on the second attempt; reuse avoids
calling it again.

A retry creates another attempt of the saved plan. It preserves earlier
attempt records. Use it after a transient failure has been resolved. Changes
to code, inputs, or settings require a new plan.

```python
from pathlib import Path
from viper import execution
from viper.repository import resolve_root

root = resolve_root()
plan_path = Path("experiments/cpu_quickstart/runs/baseline/<YOUR_RUN_ID>/spec.yaml")
retried = execution.retry(root, plan_path)
print(retried.status)
```

The plan is saved before its
stages execute. The [execution guide](execution.md#handle-a-failed-operation)
explains failure handling.

## Restore verified artifacts

Use the `result:` path printed by the CPU quickstart:

```python
from viper import execution
from viper.repository import resolve_root
from viper.restoration import ArtifactRestoreSelector

root = resolve_root()
run_path = root / "experiments/cpu_quickstart/runs/baseline/<YOUR_RUN_ID>/resolved.yaml"
restored = execution.restore(
    root,
    run_path,
    artifacts=(ArtifactRestoreSelector(stage_id="train", artifact_name="model"),),
)
for artifact in restored.artifacts:
    for file in artifact.files:
        print(file.status, file.path)
```

Each file reports `restored` or `already_present`. A bundle reports one entry
per member. Pass `output=destination_path` to select a destination. VIPER
checks source bytes and destinations before writing; it rejects a destination
that already contains different bytes.

## Inspect status and lineage

Use the saved result path and the journal path returned in `RunResult.journal_path`:

```python
from pathlib import Path

from viper import api
from viper.inspection import attempt_status
from viper.repository import read_source, resolve_root

root = resolve_root()
run_path = root / "experiments/cpu_quickstart/runs/baseline/<YOUR_RUN_ID>/resolved.yaml"
journal_path = Path("<JOURNAL_PATH>")
trusted = frozenset({str(read_source(root).repository)})
print(attempt_status(journal_path).state)
graph = api.lineage(
    api.LineageRequest(
        root=root, path=run_path, trusted_source_repositories=trusted
    )
)
for edge in graph.edges:
    print(edge)
```

The journal reports attempt progress. Lineage verifies the run and identifies
its stage, artifact, and reuse relationships.

## Compare two runs

Select the two saved results to compare:

```python
from viper import api
from viper.repository import read_source, resolve_root

root = resolve_root()
baseline_path = root / "experiments/cpu_quickstart/runs/baseline/<FIRST_RUN_ID>/resolved.yaml"
candidate_path = root / "experiments/cpu_quickstart/runs/baseline/<SECOND_RUN_ID>/resolved.yaml"
trusted = frozenset({str(read_source(root).repository)})
comparison = api.compare_runs(
    api.CompareRunsRequest(
        left_root=root, right_root=root,
        left_path=baseline_path, right_path=candidate_path,
        trusted_source_repositories=trusted,
    )
)
for change in comparison.changes:
    print(change)
```

Comparison reports differences in the saved records. Separate executions have
different IDs and timestamps even when their artifact bytes match. Inspect the
artifact digests when comparing the produced files.

The [CLI reference](../reference/cli.md) documents equivalent terminal commands.

## Resume training from a checkpoint

Retrying a failed run and continuing training from a saved checkpoint are
separate operations. A retry executes another attempt of the original plan.
To continue from a completed training stage, author a new stage with both
`model` and `resume_state` inputs from the same producer.

For two training stages in one run, start with the `training` declaration in
the [CPU quickstart](../../examples/cpu_quickstart.py) and select both output handles:

```python
checkpoint_inputs = (training.outputs["model"], training.outputs["resume_state"])
```

For a completed run, select both files with `run_artifact()` and pass them under
those same input names. Include the dataset and any other inputs your function
uses in the new stage's `inputs` tuple.

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
