# RGP-PB-01: Verified Document Reads

**Context:** The promoter duplicates local-file retrieval and hash checks.
This slice delegates identified document reads to the existing verified fetcher,
updates every constructor caller, and preserves ordinary publication behavior.

The [plan](plan.toml) owns the baseline, actions, and gate. The
[patch](patches/verified-document-reader.patch) contains the complete change to
[the promoter](../../../src/viper/execution/_promotion.py) and
[its tests](../../../tests/test_run_execution.py). The
[contract](../../../contracts/run-graph-republication.md) owns the later migration.

Apply the complete two-file patch together. It adds a required keyword-only
`fetcher` argument, so applying only the constructor change leaves callers
incomplete. The public function remains restricted to local roots in this block.

## Internal review

The review covers the complete retained patch against
`77acb8382697af7fd5eb975e3afab6791505e626`, every `_RunGraphPromoter` constructor
call, `read_local()` and its caller, `RunFetcher.read_verified()`, and the
neighboring identity/publication helpers. Live transfers and later migration
requirements are excluded from this first-slice verdict.

The invariant is that the supplied fetcher determines source retrieval and
validates the recorded identity; the promoter translates retrieval failures
while preserving their cause. Public promotion still rejects cloud roots.
An ordinary exception is translated; process cancellation through
`KeyboardInterrupt` or `SystemExit` remains outside `Exception`.

The counterexamples are a missing source, a different byte count, altered bytes
with the same length, a fetcher other than the injected instance, and premature
acceptance of a cloud root. The tests keep the real `read_verified()` code and
replace only transport. They establish delegation and validation. Live provider credentials and network
behavior require separate acceptance.

| Review item | Decision |
|---|---|
| Duplicate local reader | Remove `read_local()` and its duplicate hash/size check in the same patch as `read_document()`. |
| Constructor propagation | Supply the existing source fetcher in public promotion and an explicit fetcher in the neighboring-store test. |
| `hashlib` | Retain: `source_identity()`, plan-member identification, and final-reference verification still use it. |
| `local_artifact_store` | Retain: snapshot enumeration, source bootstrap, and plan-member discovery still use it. |
| `_publish_sources()` | Retain: neighboring-store paths still need confinement and cross-filesystem staging. |
| `source_identity()` versus `_cloud.source_file()` | Retain both in this slice: the promoter hashes neighboring-store paths before staging, while the provider helper requires paths confined to its own root. Direct substitution would break neighboring-store publication. |
| Reuse and source-closure rewriting | Retain: existing tests observe the changed reuse key and preserved artifact identities. |
| `_export._read_local()` | Retain: this is a different reader for bundle-bound historical references. |
| Future cloud pass-through removal | Assigned to later blocks; removing it now would expose incomplete discovery and rewriting. |

The first draft indexed `LocalArtifactStore.resolved_files()` as a mapping.
Pyright and the focused run rejected that test setup. The retained patch uses
tuple unpacking, matching the inspected return type. The initial run had fourteen
fixture failures and six existing promotion passes; the repaired candidate requires its own complete passing gate.

Final mechanical evidence and the bounded review verdict are recorded below
after the frozen plan's gate executes. The contract-generated handoff links the
authoritative passing receipt. Human approval and installed implementation acceptance remain separate lifecycle
events after this internal review.

The first contract-runner attempt materialized only the execution subtree. Its
Pyright step then resolved imports against the installed checkout and failed
with 26 errors. The corrected plan materializes the complete package,
`pyproject.toml`, and `pyrightconfig.json`, and explicitly selects VIPER's
interpreter. The failed attempt remains in the gate history. Its recovery also
preserved a concurrent authored-prose correction before publishing the failed
receipt through the protocol's projection transaction.

The shared contract runner uses Python 3.14 from the system framework. Its
declared Pydantic dependency was absent; installing `pydantic>=2.12,<3` resolved
Pydantic 2.14.1 and restored contract compilation. Candidate Python checks use
VIPER's existing project-local virtual environment.

## Stop condition

After applying this slice, run the exact gate commands in the plan and inspect
the resulting diff. Stop on any failure or an unexpected changed path. The next
slice begins only after the applied files match the reviewed candidate and this
bounded implementation has been reviewed and committed.

## Final evidence and verdict

The [final gate](../../../evidence/gates/rgp-pb-01-20261016-r3.json) passed
Pyright with zero errors and warnings, 22 selected tests, documentation checks
across the discovered package and test roots, Ruff format checking, and Ruff
lint checking. The gate records the exact argument vectors and outputs. The
isolated candidate uses the configured project interpreter; Pyright prints a
missing local `.venv` directory notice because the disposable candidate points
to that interpreter through `--pythonpath`.

Internal verdict: **Approve the RGP-PB-01 candidate.** Every changed line and
constructor caller was inspected. The fixture indexing error and incomplete
materialization roots were repaired and the final counterexamples pass. The
constructor now documents its binding responsibility. There are zero open
findings within this first slice. Cloud relocation, durable progress, budgets,
and real-model recovery retain their separate future acceptance requirements.

The contract and checklist compile through the shared typed protocol. Local
Markdown links resolve, authored prose passes the direct-prose checker, and all
three contract diagrams were rendered with Mermaid CLI 11.16.0 and visually
inspected in light and dark themes. The narrower vertical diagrams preserve
readable labels at document width.

The active implementation remains at the baseline pending the user's edits.
The tested review commit is `a107a9f4e1832b0410d0d9e69e056d36939b10e2`.
The contract lifecycle is `review`; human approval and implementation acceptance
remain pending. The unrelated editor-settings change remains outside this task.
