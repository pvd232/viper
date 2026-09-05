# Rename Obligation Check Source Plan

This directory retains the reviewed source plan that produced the first exact
rename-check implementation. Production behavior now belongs to
[`system_impact/rename.py`](../../src/viper/system_impact/rename.py), the typed
API, and `viper impact rename-check`.
`viper impact rename-plan` publishes the frozen baseline worklist before edits.
It also publishes `rename-worklist.json`; the stdlib-only `viper-impact`
command serves that index during the edit loop without starting CodeQL.

[`agent-experiment.md`](agent-experiment.md) records the original smoke tests
and the staged paired trial of ordinary search against the precomputed index.

`plan.toml` takes the accepted `P0-ROC-01` commit as its baseline and binds
`P0-ROC-02` to the query-derived checker and overlay optimization. `check.py`
extracts that baseline, applies the update, runs static and focused tests, then
analyzes baseline and candidate source. The checker leaves the active working
tree unchanged.

[`historical-refactor-results.md`](historical-refactor-results.md) records the
Supervision gold-patch coverage, parity, and timing observations.

Run the complete gate with the repository environment:

```bash
python plans/rename-obligation-check/check.py
```
