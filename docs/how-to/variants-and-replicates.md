# Run variants and replicates

A variant selects the computation and configuration to compare. A replicate
selects the random seed for one execution of that variant.

## Compare training-set sizes

This example trains the same linear model on either two or three CSV rows,
with two replicate seeds for each choice. The build function reads the row
limit from its config and writes the selected data. The training function
then reads that output.

Run the complete [variants example](../../examples/variants.py) from the
repository root after following the [installation steps](../tutorials/getting-started.md#install-the-repository):

```bash
python -m examples.variants
```

The program imports training from [cpu_quickstart.py](../../examples/cpu_quickstart.py)
and CSV preparation from [workflow_functions.py](../../examples/workflow_functions.py).
Keep these files in the `examples` directory and run the command from the
repository root. `limit_rows()` reads `context.config.rows`, keeps that many
CSV rows after the header, and writes them to `context.outputs["dataset"]`.

```python
"""Compare training on two or three rows across two replicate seeds."""

from examples.cpu_quickstart import fit, load_json, load_state, mse
from examples.workflow_functions import RowLimit, limit_rows, load_text
from viper import execution
from viper.authoring import (
    VariantDraft,
    expand,
    experiment,
    factor,
    input,
    replicate,
    stage,
    variant,
)
from viper.metrics import min
from viper.outputs import StageOutputs, TrainOutputs, output
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env


def training_variant(name: str, rows: int, level: str) -> VariantDraft:
    """Connect row selection to the complete quickstart training function."""
    prepared = stage(
        limit_rows,
        stage_id="prepare",
        config=RowLimit(rows=rows),
        inputs=(input("dataset", path="examples/data/tiny.csv", data_role="training"),),
        outputs=StageOutputs(
            dataset=output(path="selected.csv", loader=load_text, data_role="training")
        ),
    )
    training = stage(
        fit,
        stage_id="train",
        inputs={"dataset": prepared.outputs["dataset"]},
        outputs=TrainOutputs(
            model=output(path="model.json", loader=load_json, data_role="training"),
            resume_state=output(
                path="resume_state.pt", loader=load_state, data_role="training"
            ),
        ),
        metrics=(mse,),
        objective=min(mse),
    )
    return variant(
        name,
        levels={"training_rows": level},
        stages=(
            prepared,
            training,
        ),
        estimator=training.outputs["model"],
    )


study = experiment(
    experiment_id="training_rows",
    factors={"training_rows": factor(levels=("two", "three"))},
    variants=(
        training_variant("two_rows", 2, "two"),
        training_variant("three_rows", 3, "three"),
    ),
    replicates=(replicate(seed=7), replicate(seed=19)),
)


def main() -> None:
    """Create one plan per pair and report each batch outcome."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    drafts = expand(study, source=source, env=environment)
    root = resolve_root()
    batch = execution.run_many(root, drafts, max_concurrency=2)
    for entry in batch.runs:
        if entry.result is not None:
            print(f"{entry.run_id}: {entry.result.status} {entry.result.path}")
        elif entry.failure is not None:
            print(f"{entry.run_id}: failed {entry.failure.message}")
        else:
            print(f"{entry.run_id}: skipped {entry.skip_reason}")


if __name__ == "__main__":
    main()
```

Variants declare their names. `replicate(seed=7)` automatically names the
replicate `seed_7` and uses `7` to initialize its random generators.
The name can describe a trial instead: `replicate("trial_a", seed=7)` has the
same seed. Distinct replicates may deliberately share a seed.

`stage_id` identifies a stage within the variant. Its decorator determines
its kind. For example, two stages named `encoder` and `classifier` can both
use `@train`; the names distinguish their outputs and measurements. Tuples
preserve declaration order and reject duplicate names. Mappings remain useful
when building experiments from a configuration file; a mapping key must agree
with any name on its value.

Each factor lists the permitted labels for one experimental choice. Here
`training_rows` permits `two` and `three`. `RowLimit.rows` actually controls
which rows the function writes; the labels describe that choice. Every variant
must assign one level to every declared factor.

`expand()` creates one plan for each variant-replicate pair and generates their
run IDs. `run_many()` saves the plans and executes the batch. To run one pair
instead, call `plan()` with explicit `variant=` and `replicate=` selections.

The program prints four outcomes. The two variants learn different weights
after twenty updates. This training function uses fixed inputs and a fixed
initial weight, so changing the seed alone preserves its result.

## Supply run IDs with expand

Use `expand()` when your caller already has a run ID for every selected pair.
Inside `main()` above, replace the `drafts = expand(...)` assignment with:

```python
drafts = expand(
    study,
    run_ids={
        "two_rows": {
            "seed_7": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "seed_19": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
        },
        "three_rows": {
            "seed_7": "01ARZ3NDEKTSV4RRFFQ69G5FAX",
            "seed_19": "01ARZ3NDEKTSV4RRFFQ69G5FAY",
        },
    },
    source=source,
    env=environment,
)
```

These fixed IDs permit one batch; use fresh IDs for another. `expand()` orders
the drafts by variant declaration, then replicate declaration. To select a
subset, pass `variants=("two_rows",)` or `replicates=("seed_7",)`. When supplying
`run_ids`, restrict the mapping to exactly those pairs. Missing pairs, extra pairs, and duplicate IDs
are rejected.

For either approach, `max_concurrency` limits simultaneous local runs. See
[batch failures](execution.md#handle-partial-batch-failure) for failure and
skip outcomes.
