# Rename Obligation Check Source Plan

This directory retains the reviewed source plan that produced the first exact
rename-check implementation. Production behavior now belongs to
[`system_impact/rename.py`](../../src/viper/system_impact/rename.py), the typed
API, and `viper impact rename-check`.

[`agent-experiment.md`](agent-experiment.md) records the paired coding-agent
smoke test and its bounded conclusion.

`plan.toml` binds `P0-ROC-01` to two complete added files. `check.py` extracts
the recorded baseline into a temporary directory, adds those files, runs Ruff,
Pyright, and the focused tests, then analyzes the baseline and candidate with
one CodeQL identity. The checker leaves the active working tree unchanged.

Run the complete gate with the repository environment:

```bash
python plans/rename-obligation-check/check.py
```
