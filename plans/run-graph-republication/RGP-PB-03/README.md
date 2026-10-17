# RGP-PB-03: Publish the discovered graph to another host

Context: the complete source graph is known. The promoter now publishes its
snapshots and updates each parent to use the new child references.

## Changes

The existing snapshot and reference maps now accept cloud source addresses.
The publisher keeps each snapshot's complete file list. It checks source bytes,
rewrites the existing typed records, and preserves payload hashes. Git source
files retain their pinned source addresses. Git-hosted protocol documents can
receive additional cloud copies when they contain graph references.

The ordinary three-argument operation keeps its existing behavior. Full graph
publication is exercised through the internal promoter while the restart,
resource, comparison and cold-recovery checks are added in later blocks.

## Checks

A real HuggingFaceProvider writes to an in-memory commit API. The test compares
payload hashes, blocks every original cloud client, and runs the normal Viper
verifier on the additional graph. Repeating publication reuses the existing
snapshot maps. Original cloud bytes remain unchanged.

See `review-checks.json` for exact commands, outputs and source hashes.
Independent review is pending.

## Code growth

```text
90	41	src/viper/execution/_promotion.py
61	0	tests/fixtures.py
80	1	tests/test_run_execution.py
```
