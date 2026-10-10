# Capture scientific journals and search their learned vectors

Put `JOURNAL.md` in `experiments/<experiment_id>/`. After a successful run is
verified and saved, VIPER captures that file automatically, publishes its
paragraphs, encodes their exact text with pinned Qwen3-Embedding-0.6B, and refreshes
the local knowledge index without dropping runs or reuse candidates.

No journal means no encoder process or model download. Historical notes are
indexed when a run completes or when you publish its journal explicitly.
`RunResult.journal_path` remains the separate append-only attempt log.

## Run the complete example

With the checkout installed and its source committed, run:

```bash
python -m examples.journal_search
```

The [complete program](../../examples/journal_search.py) creates notes only when
none exist, executes the CPU training example, retrieves proposed passages
linked to that run, encodes a search question with the same pinned encoder, and
prints the nearest passages. Its [input journal](../../examples/data/JOURNAL.md)
illustrates the scientific structure below. Existing journals are not overwritten.

The first invocation downloads about 1.2 GB of weights. Float32 encoding requires
roughly 2.4 GB for weights plus activation memory. Encoding runs on CPU with one
thread in a separate process, not on the experiment's GPU. The default
600-second encoder limit covers the entire passage batch, including download
time, model loading, and CPU inference. Explicit `timeout_seconds` settings
still override that limit. Pre-download the immutable
revision when preparing a slow or offline host:

```bash
hf download Qwen/Qwen3-Embedding-0.6B \
  --revision 97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3 \
  --include '*.safetensors' --include '*.json' --include '*.txt'
```

No journal text is sent to an inference service. Hugging Face supplies model
files; encoding and the SQLite search index remain local.

## Write structured scientific prose

For the CPU quickstart, save this in `experiments/cpu_quickstart/JOURNAL.md`:

```markdown
# Experiment: CPU quickstart

## Question and hypothesis
Question: Does the toy model fit y = 2x?
Hypothesis: Training loss decreases during 20 updates.
Falsification: Final loss exceeds initial loss.
Author: Researcher

## Comparison and methods
Baseline: Initial weight 0
Candidate: Weight after 20 updates
Changed variable: Learned weight
Held constant: Dataset, update rule, device, thread count, and seed

## Observations
ID: obs-final-loss
Metric: mean_squared_error
Stage: train
Epoch: 20
The final loss is recorded in the linked saved measurement file.

## Interpretation and decision
Supports: obs-final-loss
Limitations: Training fit does not establish held-out generalization.
Next action: Evaluate on held-out data.
Supersedes: decision-previous
```

The parser stores each paragraph's exact UTF-8 bytes, original heading, and
label:value fields. Field names become lowercase with underscores, such as
`held_constant` and `next_action`; original prose is not rewritten. Hypothesis,
observation, and decision headings select claim kinds. Other sections and
unlabeled prose remain `note`. Code fences remain text and their contents do not
supply headings or fields. Duplicate fields within a paragraph and non-UTF-8
journals are rejected.

`Metric`, with optional `Stage`, `Epoch`, and `Step`, selects existing saved
measurements. `Stage`, `Epoch`, and `Step` require a `Metric` field. An unmatched
selection fails publication before assertions are published. References identify
whole measurement files; `source.fields` retains selectors for their relevant
entries. Values remain in saved measurements, not copied from an author's prose.

Every paragraph links the immutable run, which leads to its plan, source,
inputs, and runtime. `Supports` and `Supersedes` remain author-written IDs, not
verified causal or review relationships. Automatic publication always uses
`status="proposed"`, even if notes say `Review: accepted`. Explicit
`JournalAssertion` review fields are described in
[knowledge publication](catalog-knowledge-mcp.md).

## Pinning and exact-source checks

The selected revision is `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`.
The [official model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
supplies last-token pooling and L2 normalization. VIPER applies no document
prompt, text normalization, or truncation. Paragraphs over 8192 tokens are
rejected; split them at paragraph boundaries.

`JournalSource` identifies the original Markdown revision and exact byte span.
Publication checks that the span equals `JournalAssertion.text` byte for byte.
`JournalEncoding` binds the text digest to `JournalEncoderSpec`: model revision,
loaded file hashes, pooling, normalization, float32 CPU execution, eager attention,
one thread, and observed Python, platform, Transformers, PyTorch, tokenizer,
and model-file loader versions. The encoder digest is
the vector view's version. Different encoder/runtime identities are not mixed.

The [MCP regression](../../tests/test_mcp_transport.py) compares retrieved
vectors with an independent invocation on the exact source using the pinned
encoder. Manual vector publication still trusts supplied numerical values:
digest validation alone does not prove inference occurred. Embeddings support
retrieval, not scientific truth.

## Opt out or adjust the timeout

Disable automatic and explicit publication in `viper.toml`:

```toml
[journals]
enabled = false
```

Keep capture enabled and allow a longer first download or a larger journal:

```toml
[journals]
enabled = true
authored_by = "Research team"
timeout_seconds = 1200
```

`Author` overrides attribution for a paragraph; it does not grant reviewer
approval. Knowledge records remain local even when a run uses cloud storage.

## Publish an edited or historical journal without rerunning training

From a workspace with successful indexed runs, this complete program selects
one run and publishes its current journal revision:

```python
from viper import api
from viper.catalog import RunQuery, catalog
from viper.repository import read_source, resolve_root

root = resolve_root()
rows = catalog(root=root).runs(RunQuery(statuses=("succeeded",), limit=1)).items
if not rows:
    raise RuntimeError("Run an experiment first or index its saved result.")
run = rows[0]
result = api.publish_run_journal(
    api.PublishRunJournalRequest(
        root=root,
        resolved_run=root / run.run.stored_at.path,
        trusted_source_repositories=frozenset({str(read_source(root).repository)}),
    )
)
print("retained source:", result.result.source)
print("passages:", len(result.result.assertions))
print("vectors:", len(result.result.vectors))
print("skipped:", result.result.skipped)
```

Review source before granting trust. This verifies saved evidence and can run
artifact loaders, but never reruns training. `knowledge_refresh` only rebuilds
the knowledge projection; it does not parse journals. Use `publish_run_journal`
after edits to retain the new revision alongside earlier text.
Record timestamps use the linked run's completion time. Republishing unchanged
notes with the same encoder runtime returns identical assertion and vector
records; it does not create a new scientific revision merely because time passed.

The equivalent CLI command is:

```bash
viper --json knowledge journal \
  'experiments/cpu_quickstart/runs/baseline/<YOUR_RUN_ID>/resolved.yaml' \
  --root . --trust-source https://github.com/example/workspace
```

For execute-mode MCP, call `publish_run_journal` with:

```json
{
  "resolved_run": "experiments/cpu_quickstart/runs/baseline/<YOUR_RUN_ID>/resolved.yaml",
  "trusted_source_repositories": ["https://github.com/example/workspace"]
}
```

Replace the path and source URL. Read `result.source`, `result.assertions`,
`result.vectors`, and `result.skipped` inside the tool response's `result`.
Read-only clients can retrieve assertions and search vectors. Publication
requires execute-mode clients.

Set the MCP client's read timeout above `timeout_seconds` when calling
`publish_run_journal` or executing a run with a journal. For the default encoder
budget, allow 720 seconds for publication; run execution also needs time for its
stages. The encoder limit remains bounded even when the client allows more time.

## Ask a semantic question

After publishing the structured journal above, run this complete program from
the same Python environment used for publication:

```python
from viper.catalog import catalog
from viper.journals import encode_journal
from viper.knowledge import SimilarityQuery

question = "Does fitting the training data prove performance on unseen examples?"
encoded = encode_journal((question,))
matches = catalog().knowledge.similar(
    SimilarityQuery(
        view_id="journal-qwen3-0.6b",
        view_version=encoded.encodings[0].encoder_sha256,
        values=encoded.values[0],
        assertion_statuses=("proposed",),
        limit=3,
    )
)
if not matches.items:
    raise RuntimeError("Publish journal vectors with this exact encoder/runtime first.")
for match in matches.items:
    print("cosine distance:", match.distance)
    print("source:", match.source.reference)
    print("passage:", match.source.record.value.text)
```

`search_similar` through MCP accepts the same query fields, with `values` set to
the encoded question vector. The tool ranks already-published vectors; callers
encode their question first. A different encoder/runtime version returns no
matches from this view. Proposed notes stay proposed when retrieved.
Similarity is a ranking signal. Inspect the returned passage and its saved
evidence before treating the passage as an answer.

## Recover from publication failure

A parser, download, timeout, or encoder failure emits a warning after the run
is saved. Its status, artifacts, and measurements remain unchanged. Already
parsed assertions stay searchable when encoding fails. Repair the cause and
call `publish_run_journal`; do not repeat training to recover journal search.
