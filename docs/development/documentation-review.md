# Documentation review and coverage

The public documentation teaches experiment construction and execution through
Python. The CLI reference provides equivalent commands for terminal use.

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
| Durable GCS publication, restoration, and local eviction | [API reference](../reference/api.md#vipercloud), [protocol reference](../reference/protocol.md#workspace-and-cloud-paths) | [test_gcs_storage.py](../../tests/test_gcs_storage.py), [test_retention.py](../../tests/test_retention.py), and cloud-backed execution cases |
| Workspace config and validation | [Configuration](../reference/configuration.md) | `test_documented_config_stage_writes_the_selected_rows`; [test_config_validation.py](../../tests/test_config_validation.py) |
| Stateless, stateful, and configurable metrics | [Metrics](../how-to/metrics-and-benchmarks.md) | `test_documented_metrics_compute_and_persist_values`; [test_metric_interface.py](../../tests/test_metric_interface.py) |
| Stored inputs, evaluation, metric recomputation, benchmark thresholds | [evaluation.py](../../examples/evaluation.py) and [metric guide](../how-to/metrics-and-benchmarks.md) | Complete evaluation workflow; [test_prior_run_inputs.py](../../tests/test_prior_run_inputs.py), [test_benchmark_execution.py](../../tests/test_benchmark_execution.py), [test_metric_provenance.py](../../tests/test_metric_provenance.py) |
| Batch execution and partial failure | [Execution](../how-to/execution.md) | Complete variants workflow; [test_plan_execution.py](../../tests/test_plan_execution.py) |
| Retry and verified reuse | [recovery.py](../../examples/recovery.py) | Complete recovery workflow; [test_run_execution.py](../../tests/test_run_execution.py) |
| Default reuse versus fresh computation and byte comparison | [Reuse guide](../how-to/stages.md#reuse-a-verified-stage-result), [reuse.py](../../examples/reuse.py) | Complete reuse workflow verifies and restores all three model files before comparing their SHA-256 digests. |
| Checkpoint capture and restoration | [Recovery guide](../how-to/retry-restore-compare.md#resume-training-from-a-checkpoint) | `test_documented_checkpoint_round_trip`; [test_resume.py](../../tests/test_resume.py) |
| Runtime policies and recorded controls | [Configuration](../reference/configuration.md#reproducibility) | `test_policy_example_verifies_after_exit`; [test_execution_policy_controls.py](../../tests/test_execution_policy_controls.py) |
| Verification, status, lineage, comparison, restoration | [Inspection tutorial](../tutorials/inspect-results.md) | Complete inspection workflow; [test_verification_acceptance.py](../../tests/test_verification_acceptance.py), [test_inspection.py](../../tests/test_inspection.py) |
| Catalog indexing, filters, pagination, observations | [Inspection tutorial](../tutorials/inspect-results.md), [catalog guide](../how-to/catalog-knowledge-mcp.md) | Complete inspection workflow; [test_inspection.py](../../tests/test_inspection.py) |
| Knowledge record types and similarity queries | [Catalog guide](../how-to/catalog-knowledge-mcp.md#choose-a-knowledge-record) | Knowledge publication, filtering, and ranking cases in [test_inspection.py](../../tests/test_inspection.py) and [test_api.py](../../tests/test_api.py) |
| Measured diagnostic vectors and preserving knowledge refresh | [Knowledge-search tutorial](../tutorials/knowledge-search.md) | Complete knowledge workflow reads saved measurements, publishes a vector, queries it, and checks both run and reuse indexes. MCP preserving-refresh regression in [test_mcp_transport.py](../../tests/test_mcp_transport.py). |
| Portable export and offline verification | [Export guide](../how-to/retry-restore-compare.md#export-portable-evidence), [export_run.py](../../examples/export_run.py) | Complete export workflow uses `RunExportResult.bundle_path` and pins the returned manifest digest. |
| Cloud configuration, promotion, and local retention | [Cloud guide](../how-to/cloud-storage.md) | Controlled provider and retention tests; live account/bucket acceptance remains separate. |
| Public graph-based test selection | [Test-selection guide](../how-to/test-selection.md) | `test_documented_test_selection_executes` checks the printed program's selected observer and unresolved owner. |
| Typed operations, discovery, CLI and MCP exposure | [Agent interface](../reference/agents.md), [API reference](../reference/api.md), [CLI reference](../reference/cli.md) | [test_mcp_transport.py](../../tests/test_mcp_transport.py); [test_api.py](../../tests/test_api.py), [test_api_json.py](../../tests/test_api_json.py), [test_cli.py](../../tests/test_cli.py), [test_documentation.py](../../tests/test_documentation.py) |
| File and bundle outputs, immutable storage | [Inputs](../how-to/inputs.md#output-names-and-paths) | [test_output_contract.py](../../tests/test_output_contract.py), [test_artifact_validation.py](../../tests/test_artifact_validation.py), [test_storage.py](../../tests/test_storage.py) |

## Documentation checks

[test_documentation.py](../../tests/test_documentation.py) checks local links,
Python 3.11 syntax, API-operation coverage, and agreement between complete
printed programs and their source files. These structural checks complement
execution tests, which check the computed values and saved files.

The direct-call audit resolves every explicit VIPER import in current tutorials,
how-to guides, explanations, references, and shipped examples. It checks live
signatures and rejects unknown Pydantic model fields. Instance methods, values,
and snippets requiring earlier setup remain the execution tests' responsibility.
The printed MCP Python client also executes against a real stdio server.

## Review of the current checkout

The October 2026 review began at commit
`944a142c321cf742a5316a7f04c701a108e924d7`. It found and corrected these usage gaps:

- Recomputed evaluation metrics must use the same data roles as the linked
  stage's test input, split, and predictions.
- Download-root enforcement and declared Python file access were described but
  absent from the linked complete workflows. Those programs now exercise them.
- Reused runs need artifact restoration rather than reading an assumed new
  local output copy. The reuse program restores each model before comparing it.
- `ResolvedRun` exposes its spec reference, not a `.run_id` field. New examples
  retain the authored draft's run ID. Export returns `.bundle_path`, not `.path`.
- The CLI command-group summary omitted `env doctor` and `export-run`; both now
  appear alongside the complete operation table.
- Journal publication, measured-vector search, cloud promotion/retention, and
  public test selection needed usable entry points. Each now has a guide and
  links to its implementation or complete executable program.

The [journal guide](../how-to/journals.md) retains the approved scientific
structure. It also states the remaining gap: the Markdown parser, pinned learned
encoder, default-on hook, opt-out, and exact-source MCP regression are not yet
implemented. Manual assertion/vector publication must not be described as that
automatic integration. A non-alpha release claiming those features remains
blocked on their implementation and focused acceptance checks.

Historical release reports retain their version-specific APIs. Current API and
CLI tables are checked against the installed registries; they are not copied
from those historical reports.

### Validation results

The review used the checkout's `.venv`, without running the full integration or
release suite:

| Check | Observed result |
| --- | --- |
| `pyright --pythonpath .venv/bin/python` | 0 errors; the five changed/new executable examples also passed explicit type checking. |
| `python -m pytest tests -q -m 'unit or contract'` | 550 passed, 206 deselected; 11 subtests passed. |
| Documentation, public API/inventory, and workflow checks | 62 passed after the final Markdown formatting pass. |
| Focused complete workflows: stages, HTTP training, reuse, knowledge search, export | 5 passed in 82.54 seconds. Fresh, reused, and forced model files had identical SHA-256 digests. |
| Printed MCP client, discovery in both modes, and preserving-refresh execution | 4 passed in 19.08 seconds. |
| `ruff format --check src/viper tests examples docs README.md` | 194 files already formatted. |
| `ruff check src/viper tests examples` and `git diff --check` | Passed. |

The first workflow pass exposed the reuse example's assumed local output path,
which was repaired before the final five-workflow pass. A stage-pipeline attempt
also reported an implementation-module import failure; it was not reproduced in
two later focused executions. This review has not established that transient
failure's cause and does not certify every runtime edge case.

A broader `ruff check .` also finds existing style errors in the tracked
`test_script.py`, outside the Makefile's configured source gate. That scratch
script was not changed or executed by this documentation task. Live GPU/cloud
acceptance and the automatic journal feature remain separate obligations.

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
MCP transport needs the installed MCP dependency, not an external service.
Live cloud acceptance additionally needs provider dependencies, credentials,
and an accessible repository. The table maps documented workflows to tests;
its scope excludes a line-coverage
percentage or exhaustive combinations of settings.
