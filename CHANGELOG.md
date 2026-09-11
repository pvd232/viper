# Changelog

## Unreleased

- Rename the stage function's `Context` class to `StageContext`. Its fields and
  behavior are unchanged; import it from `viper.stages`.
- Accept upstream artifacts directly in stage input tuples; use
  `input(name, source=artifact)` to rename one for the receiving function.
- Accept named factors and factor-level selections as tuples. Reject duplicate
  factor names, repeated selections, and levels absent from their factor.
- Name local inputs with `input("dataset", path=..., data_role=...)` and pass
  them to `stage(inputs=(dataset,))`. Duplicate or conflicting names are rejected.
- Rename `MetricDependency.required_data_role` to `data_role` in Python and
  serialized metric declarations. Selected files must still match that role.
- Add agent discovery documentation and a stdio MCP acceptance test for both access modes.
- Bind MCP paths to the startup workspace, expose operation-specific knowledge
  query schemas, and return structured request failures with matching output schemas.
- Replace unresolved resource templates and generic prompts with supported
  references, an agent guide, and task-specific review instructions.
- Filter catalog measurements by run ID.
- Check committed plan records against their plan commit during preflight;
  source code remains bound to its separately recorded source commit.

- Generate batch run IDs in `expand()` when callers omit `run_ids`.
- Accept tuples of named stages and variants, derive replicate names from seeds,
  and reject duplicate or conflicting declaration names.
- Use the sole variant and replicate when plan selections are omitted; require
  explicit selections when several choices exist. Use decorated config defaults
  when stage config is omitted.
- Fix Python verification of mixed Git/local references and catalog indexing of
  multiple measurements from one JSONL file.
- Add complete Python inspection, stage-pipeline, HTTP-training, and recovery
  examples, with execution and documentation/source agreement checks.

- Explain stage and metric contexts before use, and provide complete batch and
  benchmark examples with their data and function definitions.
- Accept Python drafts in `execution.run_many()` and retain stored plan
  references for retries and benchmark confirmation.
- Preserve custom config fields when saving stages, variants, metrics, and
  HTTP implementations. Serialize concurrent stage imports during batch checks.
- Replace incomplete documentation examples with working implementations and
  execute the README and tutorial code blocks in acceptance tests.
- Name example metrics for their quantities: `mean_squared_error` and
  `mean_absolute_error`. Separate metric identity from its use as a training loss.
- Make the introductory metric compute mean squared error from predictions and
  targets, and show how training reads the measurement returned by `record()`.
- Give Python run and benchmark results direct `status` and `path` access, with
  the stored `record` and immutable `reference` available for inspection.
- Add guides for stage composition, execution outcomes, checkpoint resumption,
  stored inputs, and verified stage reuse.
- Correct the public API, CLI, batch, compatibility, and recovery guides; add
  configuration and metric examples and clarify verification limits.
- Fix benchmark compilation to select the evaluation stage's `test` input.
- Stop scheduling new batch runs after a failure when `stop_on_failure=True`,
  including while other runs are still active.

## 0.1.0a3 — 2026-09-07

- Remove the experimental System Impact, graph-localization, CodeQL,
  scheduling, contract-plan, fixture, and research-work surfaces from the
  public package and source distribution.
- Retain the execution, verification, storage, restoration, catalog,
  knowledge, and MCP behavior added after `0.1.0a2`.
- Keep scientific knowledge publication and exact filtered similarity search
  in the base installation, implemented by exhaustive cosine distance.
- Reject candidate wheel and source-distribution archives that contain any
  removed experimental path.
- Repair generated-project benchmark lookup so execution and verification read
  the benchmark specification from the immutable run plan.
- Align stage, artifact, parameter, resume-state, and prediction terminology
  across the retained public workflow.

- Rename metric modes to `stateful` and `stateless`. Stateful metrics accumulate
  observations through `update()` and `compute()`; stateless metrics compute
  directly from their current arguments or declared files.

## 0.1.0a2 — 2026-08-27

- Export run and benchmark results and errors from `viper.execution`.
- Normalize internal parameter, execution, verification, and application import
  paths.
- Split the public protocol into domain-owned modules and remove the retired
  `viper.protocol`, `viper.runner`, and `viper.verifier` import paths.
- Expose complete-plan operations as `viper.execution.run()`,
  `viper.execution.retry()`, and `viper.execution.benchmark()`.
- Keep the package root focused on stage decorators, runtime contexts, project
  parameter categories, and Python-entrypoint execution.
- Add `viper init` with one complete synthetic project and an installed-wheel
  acceptance test.
- Add typed stage invocation, controlled HTTP retrieval, metric recomputation,
  durable attempt files, benchmark execution, and local CPU or CUDA runtime
  evidence.
- Validate the public package on Python 3.11 through 3.14 and Pydantic 2.12.
- Publish a focused public repository with task-based documentation and one
  executable example.

## 0.1.0a1 — 2026-08-25

- Define the v3 run-plan, stage, artifact, attempt, evaluation, benchmark, and
  resolved-record contracts.
- Verify immutable file identity and cross-record provenance relationships.
- Capture and restore main-process, optimizer, and stateful DataLoader
  resume state.
- Add role-specific metric examples and repository-relative metric and loader
  bindings.
- Add extensible versioned parameter mappings for project-defined stages and
  metrics.
- Publish the `viper-provenance` distribution with the `viper` package and
  command.
- Reserve `parameters`, `resume_state`, and `predictions` while leaving user
  source layout and prediction representation project-defined.
- Separate the installed runtime package from repository documentation,
  historical designs, and examples.
- Consolidate record encoding and YAML parsing in `serialization.py`.
- Expose run, retry, and benchmark operations through `viper.execution`.
