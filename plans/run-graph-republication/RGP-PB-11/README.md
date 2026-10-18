# RGP-PB-11: Reuse recovery request reads

Context: RICO rereads requests and repeats the same model-pointer hash across seeds. Reuse the same raw bytes within each invocation while retaining every registration integrity check.

Requirement: RGP-REQ-13. Dependency: RGP-PB-08. Repository: RICO.
Planning baseline inspected: `cd81561d331f9d0a5fed7d16cc1892abffd0611a`.
Recheck HEAD before freezing the implementation candidate.

## Targets and handoff

- `tools/graph_publication/checks.py`
- `tests/test_graph_publication.py`

Use the [impact decision](../../../contracts/run-graph-republication-optimization-impact.md)
and typed verifier RGP-VR-13. Complete the bounded edit and observing tests,
then persist one `plan.toml` with its full patch and exact baseline. This note
is planning metadata. The complete patch is frozen at the implementation handoff.

## Focused gate

After materializing and repairing imports/formatting at the real target paths,
run the owning project environment's commands in this order:

```bash
pyrefly check tools/graph_publication tests/test_graph_publication.py
python -m pytest -q tests/test_graph_publication.py
ruff check --select D tools/graph_publication tests/test_graph_publication.py
ruff format --check tools/graph_publication tests/test_graph_publication.py
ruff check tools/graph_publication tests/test_graph_publication.py
```

Documentation discovery covers active source and test roots, including any new
modules. Inspect changed schema fields if the candidate introduces any; the
selected design preserves the existing schemas. Reuse connected existing fixtures.
Broaden tests only for a newly identified caller or changed shared fixture.
Live publication, GPU inference, and the full repository suite are excluded
unless the implemented diff reaches those boundaries.

**Stop condition:** One request read per request and one digest per distinct pointer per invocation; request/report bytes and saved predictions remain identical; changed pointers, reports, predictions, and invalid aliases still fail.
Retain exact command results, before/after operation counts, and production
line additions/deletions. A failed check returns the candidate to authoring.
