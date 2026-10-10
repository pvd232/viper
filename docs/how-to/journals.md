# Keep an experiment journal and publish its observations

Keep hypotheses, procedures, measurements, and conclusions separate. Preserve
corrections by naming the earlier conclusion they replace, rather than deleting
the earlier record.

## Current executable path

Write the journal in your experiment directory, then publish bounded statements
with `JournalAssertion` and immutable `JournalEvidence` references. The complete
[knowledge-search program](../../examples/knowledge_search.py) generates its run,
reads saved measurements, publishes a proposed observation, preserves the run
index, and retrieves the result. Run it with:

```bash
python -m examples.knowledge_search
```

The [inspection tutorial](../tutorials/inspect-results.md) also demonstrates
manual observation publication. `status="reviewed"` or `status="rejected"`
requires both `reviewed_by` and `reviewed_at`. An `exclusion` additionally
requires effect or impact evidence.

`RunResult.journal_path` is a different journal: VIPER's append-only attempt
transition log. It records execution progress, not scientific prose.

The current implementation does not read `JOURNAL.md` automatically. Neither
run completion nor `knowledge_refresh` parses journal files or invokes a text
encoder. `JournalVectorView` declares an embedding space, but publication of a
`KnowledgeVector` does not compute its values or prove an encoder produced them.

## Approved journal structure — pending implementation

The following structure is approved for the journal parser and default-on
publication hook. It is a writing template today, not a supported configuration
or an executable schema. The parser, encoder hook, and opt-out are not implemented.

```markdown
# Experiment: training rows

## Question and hypothesis
Question: Does retaining the third training row reduce held-out RMSE?
Hypothesis: The three-row variant will have lower held-out RMSE.
Falsification: Matched-seed held-out results do not support that improvement.

## Comparison and methods
Baseline: two_rows
Candidate: three_rows
Changed variable: RowLimit.rows, from 2 to 3
Held constant: training function, update count, optimizer, held-out data,
split, metric implementation, scoring device, thread count, and matched seeds

## Execution
Record each immutable plan, input, runtime, and completed run reference.
Use the references returned by VIPER, not a copied filename alone.

## Observations
Assign each observation an ID, retain its exact text, and name the specific
measurement references supporting it. Read values from saved measurements.

## Interpretation and decision
Name the supporting observation IDs, limitations, and next action.
Record the author and review status.
When correcting a conclusion, name the conclusion it supersedes and why.
```

The planned hook will attach observed execution references; authors supply the
question, hypothesis, controls, interpretation, and decision. A run link gives
context. Specific measurement links support an observation. Neither establishes
a causal conclusion by itself.

Qwen3-Embedding-0.6B is the selected learned encoder for the pending hook. The
required regression must bind each vector to the exact retained source text and
pinned encoder revision and preprocessing. Embedding provides retrieval; parsing
and reference validation provide structure. Legacy Markdown must retain its
original text and corrections without automatically marking claims reviewed.
