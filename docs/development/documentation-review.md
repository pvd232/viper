# Documentation review and coverage

The public documentation teaches experiment construction and execution through
Python. The CLI reference provides equivalent commands for terminal use.

## Comparison criteria

This review used the following published examples as structural references:

- [Stripe's Python setup guide](https://docs.stripe.com/get-started/development-environment?lang=python)
  connects installation to a complete request and its output. VIPER's tutorials
  must likewise include imports, source files, execution, and observable results.
- [NVIDIA NeMo's Python training guide](https://docs.nvidia.com/nemo-framework/user-guide/25.02/nemo-2.0/index.html)
  constructs model, data, and trainer objects before calling training. This
  comparison concerns the structure of that archived guide. VIPER likewise introduces objects before their consumers.
- [Stripe's error reference](https://docs.stripe.com/api/errors?lang=python)
  describes returned error fields. VIPER distinguishes raised exceptions,
  dispatched failure models, and failed entries in a completed batch.
- [Weights & Biases run identifiers](https://docs.wandb.ai/models/runs/run-identifiers)
  and [Ray Tune repetition](https://docs.ray.io/en/latest/tune/api/doc/ray.tune.search.Repeater.html)
  generate identifiers and permit optional labels. VIPER
  derives `seed_7` from `replicate(seed=7)` and permits an optional override.
- [Azure ML inputs](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-read-write-data-v2?view=azureml-api-2)
  use mapping keys, while [SageMaker processing inputs](https://sagemaker.readthedocs.io/en/stable/_modules/sagemaker/core/processing.html)
  accept names on input objects. VIPER retains input mapping keys because they
  directly identify the corresponding `context.inputs` entries. Data roles
  remain explicit so authors identify held-out data independently of stage kind.

VIPER uses these comparisons to remove redundant declarations and introduce
objects before their first use. Config defaults come from the decorated class;
a plan selects a sole variant and replicate; batch expansion generates run IDs.
Ambiguous selections, conflicting names, and invalid settings fail explicitly.

## Core workflow coverage

The linked tests own the behavior described by each guide. Complete-program
tests use temporary Git workspaces and inspect the resulting files. Unit and
contract tests cover invalid declarations and failure branches that would
obscure the introductory programs.

| Functionality | Python documentation or example | Observing tests |
| --- | --- | --- |
| Source discovery, environment, planning, training, outputs | [CPU tutorial](../tutorials/getting-started.md) | [test_readme_workflow.py](../../tests/test_readme_workflow.py): `test_cpu_quickstart_executes_and_verifies_one_run`, source-discovery tests |
| Named stages, variants, replicates, factor levels, expansion | [Variants](../how-to/variants-and-replicates.md) | [test_authoring.py](../../tests/test_authoring.py); complete variants workflow in [test_readme_workflow.py](../../tests/test_readme_workflow.py) |
| Build, embed, train, diagnostic, same-run inputs | [Stage pipeline](../tutorials/stages.md) | `test_extended_examples_execute_complete_workflows[stages.py]`; [test_diagnostic_stage.py](../../tests/test_diagnostic_stage.py) |
| HTTP retrieval and downstream training | [Inputs](../how-to/inputs.md), [download_training.py](../../examples/download_training.py) | Complete download workflow; redirect, credential, digest, size, and timeout cases in [test_http_retrieval.py](../../tests/test_http_retrieval.py) |
| Workspace config and validation | [Configuration](../reference/configuration.md) | `test_documented_config_stage_writes_the_selected_rows`; [test_config_validation.py](../../tests/test_config_validation.py) |
| Stateless, stateful, and configurable metrics | [Metrics](../how-to/metrics-and-benchmarks.md) | `test_documented_metrics_compute_and_persist_values`; [test_metric_interface.py](../../tests/test_metric_interface.py) |
| Stored inputs, evaluation, metric recomputation, benchmark thresholds | [evaluation.py](../../examples/evaluation.py) and [metric guide](../how-to/metrics-and-benchmarks.md) | Complete evaluation workflow; [test_prior_run_inputs.py](../../tests/test_prior_run_inputs.py), [test_benchmark_execution.py](../../tests/test_benchmark_execution.py), [test_metric_provenance.py](../../tests/test_metric_provenance.py) |
| Batch execution and partial failure | [Execution](../how-to/execution.md) | Complete variants workflow; [test_plan_execution.py](../../tests/test_plan_execution.py) |
| Retry and verified reuse | [recovery.py](../../examples/recovery.py) | Complete recovery workflow; [test_run_execution.py](../../tests/test_run_execution.py) |
| Checkpoint capture and restoration | [Recovery guide](../how-to/retry-restore-compare.md#resume-training-from-a-checkpoint) | `test_documented_checkpoint_round_trip`; [test_resume.py](../../tests/test_resume.py) |
| Runtime policies and recorded controls | [Configuration](../reference/configuration.md#reproducibility) | `test_policy_example_verifies_after_exit`; [test_execution_policy_controls.py](../../tests/test_execution_policy_controls.py) |
| Verification, status, lineage, comparison, restoration | [Inspection tutorial](../tutorials/inspect-results.md) | Complete inspection workflow; [test_verification_acceptance.py](../../tests/test_verification_acceptance.py), [test_inspection.py](../../tests/test_inspection.py) |
| Catalog indexing, filters, pagination, observations | [Inspection tutorial](../tutorials/inspect-results.md), [catalog guide](../how-to/catalog-knowledge-mcp.md) | Complete inspection workflow; [test_inspection.py](../../tests/test_inspection.py) |
| Knowledge record types and similarity queries | [Catalog guide](../how-to/catalog-knowledge-mcp.md#choose-a-knowledge-record) | Knowledge publication, filtering, and ranking cases in [test_inspection.py](../../tests/test_inspection.py) and [test_api.py](../../tests/test_api.py) |
| Typed operations, discovery, CLI and MCP exposure | [API reference](../reference/api.md), [CLI reference](../reference/cli.md) | [test_api.py](../../tests/test_api.py), [test_api_json.py](../../tests/test_api_json.py), [test_cli.py](../../tests/test_cli.py), [test_documentation.py](../../tests/test_documentation.py) |
| File and bundle outputs, immutable storage | [Inputs](../how-to/inputs.md#output-names-and-paths) | [test_output_contract.py](../../tests/test_output_contract.py), [test_artifact_validation.py](../../tests/test_artifact_validation.py), [test_storage.py](../../tests/test_storage.py) |

## Documentation checks

[test_documentation.py](../../tests/test_documentation.py) checks local links,
Python 3.11 syntax, API-operation coverage, and agreement between complete
printed programs and their source files. These structural checks complement
execution tests, which check the computed values and saved files.

Run the public-documentation tests with:

```bash
python -m pytest tests/test_documentation.py tests/test_public_inventory.py tests/test_readme_workflow.py -q
```

Changes to authoring, verification, and cataloging also require `make check`
and `make check-integration` as defined in [Testing VIPER](testing.md).

## Environment boundaries

The HTTP example's automated test uses the real client against a local server,
retaining the documented CSV digest. GitHub availability remains dependent on the external service.
GPU execution requires [the live CUDA checks](testing.md#run-the-validation-gates).
Cloud storage and MCP transport also require their configured service or
optional dependencies; live service acceptance requires execution against those services. The table
maps documented workflows to tests; its scope excludes a line-coverage
percentage or exhaustive combinations of settings.
