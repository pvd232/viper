# Unreleased changes

## Snapshot reference imports

Import `StageResultSnapshotRef` from
[`viper.references`](../../src/viper/references.py) in place of
`viper.references.StageResultSnapshot` or `viper.evidence.StageSnapshot`.
The canonical name identifies the existing union of local, Hugging Face, GCS,
and ViperCloud snapshot references. The two old Python aliases are removed.

Saved JSON/YAML fields, storage addresses, and verification behavior remain
unchanged. Local snapshot references identify `workspace / store / commit`;
file references add `path`. The `store_id` must match the random identity saved
in the store's `.identity` file. Local `commit` is a content revision derived
from file paths, sizes, and hashes.
