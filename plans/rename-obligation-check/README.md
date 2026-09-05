# Rename Obligation Check Source Plan

This directory contains the reviewed implementation of the exact rename
checker proposed by the [Rename Obligation Check contract](../../docs/development/rename-obligation-check.md).

`plan.toml` binds `P0-ROC-01` to two complete added files. `check.py` extracts
the recorded baseline into a temporary directory, adds those files, runs Ruff,
Pyright, and the focused tests, then analyzes the baseline and candidate with
one CodeQL identity. The checker leaves the active working tree unchanged.

Run the complete gate with the repository environment:

```bash
python plans/rename-obligation-check/check.py
```
