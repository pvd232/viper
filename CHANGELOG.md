# Changelog

## 0.1.0a2 — 2026-08-27

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
