# RGP-PB-06: Compare the original and additional publications

Context: a copied graph can pass ordinary validation while pointing to a different valid input. This check compares each saved source relationship with its recorded destination copy.

## Implementation

`GraphComparison` reads the journal's file mappings and compares original and destination files through separate caches. It checks complete snapshot membership, selected roots, required inventory entries, payload hashes, and the exact destination repository.

For saved protocol documents, it derives the permitted location and hash changes from the original record. The check preserves parameters, measurements, source commits, input names, and list membership. It also checks the derived stage-plan hashes, reuse keys, and download-source receipt identifiers. The comparison code runs independently of the promoter's rewrite methods.

When rewriting an older typed document materializes omitted schema defaults, the comparison fills those defaults from the source document's defining model. Explicit source values remain unchanged, and the destination is compared without normalization. Unchanged documents retain their original field sets. Regression cases reject altered or missing defaults, unexpected fields, and changed configuration values.

An operation can use the same working-space limit for its separate source and destination check caches. Verified temporary downloads are removed after each comparison; original files remain intact.

The worker's `verify_only=True` option requires a complete journal covering exactly the discovered snapshots. It reuses their saved destinations and reruns comparison and destination loading without publishing or changing the journal. Empty and incomplete journals are rejected before any upload.

## Checks

20 focused cases passed in 20.69 seconds. Pyright, docstring checks, formatting and lint checks passed. Exact commands and hashes are recorded in [review-checks.json](review-checks.json).

The new cases cover a complete mixed-cloud graph, an altered seed, a missing required file, and substitution of a separately valid plan. The substituted plan passes the ordinary graph verifier and fails this source-to-destination comparison.

The October 18 repair passed 13 focused comparison, resource, and worker cases locally (55.03 seconds) and on the source VM (104.58 seconds). The exact source and destination stage documents that stopped the live comparison also matched after source-only default expansion. Empty and incomplete journals failed verification-only resume; a complete journal passed with publication disabled and its mapping digest unchanged.

Full-project Pyrefly and Ruff passed locally. The fast gate passed 593 tests and 11 subtests in 48.24 seconds; integration passed 213 tests and 28 subtests in 1,109.26 seconds. At the real VM target paths, focused Pyrefly and Ruff passed. The VM's separate whole-project Pyrefly scan reported a missing `transformers` import in the unrelated journal encoder; the original numerical environment was preserved. These source checks do not by themselves establish completion of the live graph comparison.

## Size and review

Production grows by 297 lines and tests by 183 lines. The comparison owns the required independent check; it consumes the existing file references, manifests, journal, and source readers. Git records the implementation directly. Independent review is pending.
