# Versioning policy

VIPER uses package versions of the form `major.minor.patch`. For stable releases
(1.0 and later):

- Increase `major` when a released Python API or serialized protocol contract
  changes incompatibly.
- Increase `minor` when a backward-compatible document, verifier operation,
  loader, metric, or command is added.
- Increase `patch` for backward-compatible corrections that preserve the
  existing public contract.

The package version and each document's `schema_version` serve different roles. The
package version identifies a software release. A document's `schema_version` selects its
parser and validation contract.

Alpha releases use PEP 440 pre-release versions such as `0.1.0a1`. During the `0.x`
series, each release note must identify every incompatible change.

## Compatibility in 0.1.0a3

Stage documents use schema version 2. Regenerate version-1 stage documents with the
current authoring API; the parser rejects them with a migration error. Other record
types have their own schema versions. Query the installed schema before constructing a
record directly.

Use `viper.serialization.serialize_document()` to encode a validated record. The
`serialize_record()` alias has been removed.

The [release report](../releases/0.1.0a3.md) lists the Python API and protocol changes
in this candidate.
