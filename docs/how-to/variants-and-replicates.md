# Run variants and replicates

A variant chooses one stage graph and its factor levels. A replicate supplies a
reproducible seed. Their Cartesian product defines the runs in an experiment.

## Declare factors and variants

```python
from viper.authoring import experiment, factor, replicate, variant

study = experiment(
    experiment_id="optimizer-study",
    factors={"optimizer": factor(levels=("adam", "sgd"))},
    variants={
        "adam": variant(
            levels={"optimizer": "adam"},
            stages={"train": adam_training},
            estimator=adam_training.artifacts["model"],
        ),
        "sgd": variant(
            levels={"optimizer": "sgd"},
            stages={"train": sgd_training},
            estimator=sgd_training.artifacts["model"],
        ),
    },
    replicates={
        "seed_7": replicate(seed=7),
        "seed_19": replicate(seed=19),
    },
)
```

Every variant must assign one level for every declared factor. Every estimator
must be an artifact produced by that variant's stage graph.

## Create one plan

Use `plan()` when you want one selected variant-replicate pair:

```python
draft = plan(
    experiment=study,
    variant="adam",
    replicate="seed_7",
    source=source,
    env=environment,
    reproducibility=reproducibility,
)
result = execution.run(root, draft)
```

## Expand the experiment

Use `expand()` to create an ordered plan for every selected pair. Freeze those
plans, then execute their paths with bounded concurrency:

```python
result = execution.run_many(
    root,
    run_spec_paths,
    max_concurrency=2,
    stop_on_failure=False,
)
```

`max_concurrency` limits simultaneous local runs. It does not change the
experiment's variant or replicate identity.
