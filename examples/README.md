# VIPER examples

Run these commands from the repository root after following the
[installation instructions](../docs/tutorials/getting-started.md#install-the-repository).
Each run reads committed source and writes results under `experiments`.

| Example | Command | Result |
| --- | --- | --- |
| [CPU quickstart](cpu_quickstart.py) | `python examples/cpu_quickstart.py` | Fits a linear model and saves its model and checkpoint. |
| [Execution policies](execution_policies.py) | `python examples/execution_policies.py relaxed` | Runs the quickstart with the selected policy; also accepts `reproducible` and `custom`. |
| [Variants and replicates](variants.py) | `python -m examples.variants` | Trains on two or three rows under two seeds and reports all four batch outcomes. |
| [Evaluation and benchmark](evaluation.py) | `python -m examples.evaluation` | Saves held-out data, trains and evaluates the model, then independently confirms the benchmark. |
| [Stage pipeline](stages.py) | `python -m examples.stages` | Prepares data, computes features, trains, and writes a diagnostic report. |
| [Inspection and queries](inspect_results.py) | `python -m examples.inspect_results` | Verifies, compares, restores, paginates measurements, and publishes an observation. |
| [HTTP training](download_training.py) | `python -m examples.download_training` | Downloads the pinned CSV before training. |
| [Recovery and reuse](recovery.py) | `python -m examples.recovery` | Retries an intentional first-attempt failure, then reuses the verified result. |

[workflow_functions.py](workflow_functions.py) contains the CSV preparation,
output loader, prediction, and RMSE functions used by the extended examples.
The scripts import those complete implementations. Keep that file and
[cpu_quickstart.py](cpu_quickstart.py) alongside the scripts when copying them.

The training data is [tiny.csv](data/tiny.csv). The benchmark uses distinct
observations from [held_out.csv](data/held_out.csv) and selects rows 0 and 2.
Both files describe the simulated relation `y = 2x`.

The [variants guide](../docs/how-to/variants-and-replicates.md) explains factor
labels, config values, and batch outcomes. The [metrics guide](../docs/how-to/metrics-and-benchmarks.md)
explains measurement recording, recomputation, and benchmark thresholds.

To check the examples from a clean temporary workspace:

```bash
python -m pytest tests/test_readme_workflow.py -q
```
