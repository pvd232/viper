# Changelog

## 0.1.0a1 — unreleased

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
