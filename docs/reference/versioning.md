# Versioning policy

VIPER provenance uses semantic package versions of the form
`major.minor.patch`.

- Increase `major` when a released Python API or serialized protocol contract
  changes incompatibly.
- Increase `minor` when a backward-compatible document, verifier operation,
  loader, metric, or command is added.
- Increase `patch` for backward-compatible corrections that preserve the
  existing public contract.

The package version and each document's `schema_version` serve different roles.
The package version identifies a software release. A document's `schema_version`
selects its parser and validation contract.

Alpha releases use PEP 440 pre-release versions such as `0.1.0a1`. During the
`0.x` series, each release note must identify every incompatible change.

## Scheduled compatibility changes

`serialize_record()` remains available in `0.1.x` and emits a
`DeprecationWarning`. VIPER removes this alias in `0.2.0`.
`serialize_document()` is the supported encoder.
