# Run variants and replicates

A variant selects a stage graph and factor levels. A replicate supplies a seed. Run each
selected variant with each selected replicate to compare the variants under the same
seeds.

## Declare factors and variants

Start with two training stages, `adam_training` and `sgd_training`, declared as in the
[CPU tutorial](../tutorials/getting-started.md). Each stage must actually use the named
optimizer in its function or config; factor labels describe the choice while the
function and config determine training behavior.

```python
from viper.authoring import experiment, factor, replicate, variant

study = experiment(
    experiment_id="optimizer_study",
    factors={"optimizer": factor(levels=("adam", "sgd"))},
    variants={
        "adam": variant(
            levels={"optimizer": "adam"},
            stages={"train": adam_training},
            estimator=adam_training.outputs["model"],
        ),
        "sgd": variant(
            levels={"optimizer": "sgd"},
            stages={"train": sgd_training},
            estimator=sgd_training.outputs["model"],
        ),
    },
    replicates={
        "seed_7": replicate(seed=7),
        "seed_19": replicate(seed=19),
    },
)
```

Every variant assigns one level to each declared factor. Its estimator selects an output
from its stage graph. Reuse the source, environment, and reproducibility records from
your experiment setup in the following calls.

## Create one plan

`plan()` assigns a new run ID to one selected pair:

```python
from viper import execution
from viper.authoring import plan

draft = plan(
    experiment=study,
    variant="adam",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)
result = execution.run(draft, repository_root=root)
```

## Expand the experiment

`expand()` returns a tuple of drafts in variant declaration order, then replicate
declaration order. Supply a distinct run ID for each selected pair. This example uses
fixed IDs to show the mapping; assign new IDs for a new batch.

```python
from viper.authoring import expand, freeze_run_plan

drafts = expand(
    study,
    run_ids={
        "adam": {
            "seed_7": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "seed_19": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
        },
        "sgd": {
            "seed_7": "01ARZ3NDEKTSV4RRFFQ69G5FAX",
            "seed_19": "01ARZ3NDEKTSV4RRFFQ69G5FAY",
        },
    },
    source=source,
    env=environment,
    reproducibility=reproducibility,
)
frozen = tuple(freeze_run_plan(root, draft) for draft in drafts)
run_spec_paths = tuple(root / item.reference.stored_at.path for item in frozen)
result = execution.run_many(
    root,
    run_spec_paths,
    max_concurrency=2,
    stop_on_failure=False,
)
```

To select a subset, pass `variants=("adam",)` or `replicates=("seed_7",)` and restrict
`run_ids` to exactly those pairs. Missing pairs, extra pairs, and duplicate run IDs are
rejected.

`max_concurrency` limits simultaneous local runs. Inspect `result.runs` for each run's
outcome, including failures returned by a completed batch.
