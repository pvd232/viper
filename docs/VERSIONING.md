# Versioning policy

VIPER provenance uses semantic package versions of the form
`major.minor.patch`.

- Increase `major` when a released Python API or serialized protocol contract
  changes incompatibly.
- Increase `minor` when a backward-compatible record, verifier operation,
  loader, metric, or command is added.
- Increase `patch` for backward-compatible corrections that do not add a
  public contract.

The package version and each record's `schema_version` serve different roles.
The package version identifies a software release. A record's `schema_version`
selects the parser and validation contract for that serialized record.

Releases begin at `0.1.0` while the public API is alpha. During the `0.x`
series, each release note must call out any incompatible change explicitly.

## Scheduled compatibility changes

`serialize_record()` remains available in `0.1.x` and emits a
`DeprecationWarning`. VIPER removes this alias in `0.2.0`.
`serialize_document()` is the supported encoder.
