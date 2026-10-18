# RGP-PB-09: Reuse publication identities

Context: The journal and provider hash the same upload inputs, and two HF verification sites read each full manifest twice. Reuse existing prepared identities and complete manifest equality while retaining destination readback.

Requirement: RGP-REQ-11. Dependency: RGP-PB-08. Repository: VIPER.
Planning baseline inspected: `462b2029c5ec6797585840fdf8bfd7c9be886b31`.
Recheck HEAD before implementation and retain the tested commit.

## Targets and handoff

- `src/viper/execution/_promotion_journal.py`
- `src/viper/execution/_promotion_compare.py`
- `tests/test_cloud_service.py`
- `tests/test_run_execution.py`

Use the [impact decision](../../../contracts/run-graph-republication-optimization-impact.md)
and typed verifier RGP-VR-11. Complete the bounded edit and observing tests,
then commit the real target files and create a linked implementation PR. This
note defines scope and checks; Git owns the source and the PR diff owns review.
**Validation:** Complete; [results and measurements](../../../evidence/rgp-pb09-validation.json).
**PR:** Being created from `rgp/pb09-prepared-publication`. Update the [contract tracking table](../../../contracts/run-graph-republication.md#pr-review-and-integration)
when the PR exists. Keep validation, review, and integration separate.

## Focused gate

After materializing and repairing imports/formatting at the real target paths,
run the owning project environment's commands in this order:

```bash
pyrefly check src/viper tests
python -m pytest -q tests/test_cloud_service.py tests/test_run_execution.py -k "republication or promotion or copy_worker or hugging_face or streamed_hub"
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

**Stop condition:** One VIPER source hash per input per attempt; one HF manifest read at each verification site; changed bytes remain pending, lost-response commits are reused, and the substituted ancestor still fails.
Retain exact command results, before/after operation counts, and production
line additions/deletions. A failed check returns the candidate to authoring.
