# Unreleased changes

## Snapshot reference imports

Import `StageResultSnapshotRef` from
[`viper.references`](../../src/viper/references.py) in place of
`viper.references.StageResultSnapshot` or `viper.evidence.StageSnapshot`.
The canonical name identifies the existing union of local, Hugging Face, GCS,
and ViperCloud snapshot references. The two old Python aliases are removed.

The alias rename preserves saved JSON/YAML fields and storage behavior.

## Local references use content revisions

`LocalFileRef` and `LocalStageResultSnapshotRef` remove `store_id`.
Local snapshot references identify `workspace / store / commit`; file references
add `path`. Local `commit` is derived from file paths, sizes, and hashes.
Rebuilding the same files at the recorded address preserves their references.
Path confinement, file-size checks, and SHA-256 verification remain in place.

This is an incompatible document change: existing local records require
migration before loading with this version. Original publications and model
pointers remain unchanged. The previous release continues to read original
records; this release contains no compatibility parser or identity-file logic.

The [migration record](store-id-removal-20261018.md) records the inventory,
converted catalog roots, preservation checks, and validation.
