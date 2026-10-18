# RGP-PB-10: Count both disk budgets once

Context: TransferSpace scans the nested cache twice per check. One traversal must return both totals with separate inode and symlink-confinement accounting.

Requirement: RGP-REQ-12. Dependency: RGP-PB-09. Repository: VIPER.
Planning baseline inspected: `462b2029c5ec6797585840fdf8bfd7c9be886b31`.
Recheck HEAD before implementation and retain the tested commit.

## Targets and handoff

- `src/viper/execution/_promotion_transfer.py`
- `tests/test_cloud_service.py`
- `tests/test_run_execution.py`

Use the [impact decision](../../../contracts/run-graph-republication-optimization-impact.md)
and typed verifier RGP-VR-12. Complete the bounded edit and observing tests,
then commit the real target files and create a linked implementation PR. This
note defines scope and checks; Git owns the source and the PR diff owns review.
**Validation:** Complete; [results](../../../evidence/rgp-pb10-validation.json).
**PR:** Being created from `rgp/pb10-single-space-scan`. Update the [contract tracking table](../../../contracts/run-graph-republication.md#pr-review-and-integration)
when the PR exists. Keep validation, review, and integration separate.

## Focused gate

After materializing and repairing imports/formatting at the real target paths,
run the owning project environment's commands in this order:

```bash
pyrefly check src/viper tests
python -m pytest -q tests/test_cloud_service.py tests/test_run_execution.py -k "resource_limits or transfer_space or directory_bytes"
ruff check --select D src/viper tests
ruff format --check src/viper tests
ruff check src/viper tests
```

Documentation discovery covers active source and test roots, including any new
modules. Inspect changed schema fields if the candidate introduces any; the
selected design preserves the existing schemas. Reuse connected existing fixtures.
Broaden tests only for a newly identified caller or changed shared fixture.
Live publication, GPU inference, and the full repository suite are excluded
unless the implemented diff reaches those boundaries.

**Stop condition:** One directory visit per check; identical totals on fixed trees; escaping links, cross-boundary hard links, reservations, cleanup and peak accounting preserve their existing outcomes.
Retain exact command results, before/after operation counts, and production
line additions/deletions. A failed check returns the candidate to authoring.
