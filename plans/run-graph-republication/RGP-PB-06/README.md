# RGP-PB-06: Compare the original and additional publications

Context: a copied graph can pass ordinary validation while pointing to a different valid input. This check compares each saved source relationship with its recorded destination copy.

## Implementation

`GraphComparison` reads the journal's file mappings and compares original and destination files through separate caches. It checks complete snapshot membership, selected roots, required inventory entries, payload hashes, and the exact destination repository.

For saved protocol documents, it derives the permitted location and hash changes from the original record. The check preserves parameters, measurements, source commits, input names, and list membership. It also checks the derived stage-plan hashes, reuse keys, and download-source receipt identifiers. The comparison code runs independently of the promoter's rewrite methods.

An operation can use the same working-space limit for its separate source and destination check caches. Verified temporary downloads are removed after each comparison; original files remain intact.

## Checks

20 focused cases passed in 20.69 seconds. Pyright, docstring checks, formatting and lint checks passed. Exact commands and hashes are recorded in [review-checks.json](review-checks.json).

The new cases cover a complete mixed-cloud graph, an altered seed, a missing required file, and substitution of a separately valid plan. The substituted plan passes the ordinary graph verifier and fails this source-to-destination comparison.

## Size and review

Production grows by 297 lines and tests by 183 lines. The comparison owns the required independent check; it consumes the existing file references, manifests, journal, and source readers. Git records the implementation directly. Independent review is pending.
