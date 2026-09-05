# Agent Graph-Memory Experiment Source Plan

This source-backed plan owns the apparatus and evidence for the three-arm
comparison defined by
[`agent-graph-memory-experiment.md`](../../docs/development/agent-graph-memory-experiment.md).

`P0-AGM-01` adds the VIPER stage, one-pass CodeQL projection, read-only
`unresolved()` predicate, experiment authoring, verified comparison, and focused tests.
`P0-AGM-02` runs the accepted apparatus and adds the verified result report.

The completed pilot is reported in [results.md](results.md). All three runs
passed VIPER provenance verification; none passed the hidden evaluator.

The three prompts are deliberately short. The ordinary arm receives the task.
The static-graph arm also receives one flat typed relationship file. The
predicate arm receives the same file and one command that returns the current
set difference between baseline obligations and candidate relationships.

Run the isolated planned-source gate with the repository environment:

```bash
python plans/agent-graph-memory-experiment/check.py
```

After `P0-AGM-01` passes, run the pilot with:

```bash
python plans/agent-graph-memory-experiment/experiment.py \
  /tmp/viper-agent-graph-memory-pilot \
  --model gpt-5.4-mini \
  --timeout-seconds 480
```
