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

## Current checkout defaults

Workspace stages now default to `reuse="verified"` in Python authoring and
parsed stage specifications. A specification that explicitly records
`reuse="never"` still forces computation. An older stage document that omitted
`reuse` now receives the verified default when parsed; save `reuse="never"`
explicitly when fresh computation is required. Benchmark confirmation remains
independent. See [verified reuse](../how-to/stages.md#reuse-a-verified-stage-result).

These changes are listed under Unreleased in the [changelog](../../CHANGELOG.md).
The approved journal parser and encoder hook are not part of the current API;
see [the journal guide](../how-to/journals.md).

## Compatibility in 0.1.0a4

Stage documents use schema version 2. Regenerate version-1 stage documents with the
current authoring API; the parser rejects them with a migration error. Other record
types have their own schema versions. Query the installed schema before constructing a
record directly.

`LocalFileRef` and `LocalStageResultSnapshotRef` require `workspace` and
`store_id`. Regenerate local references with 0.1.0a4; earlier local references
lack enough information to distinguish two workspace stores.

Use `viper.serialization.serialize_document()` to encode a validated record. The
`serialize_record()` alias has been removed.

Newly frozen `StoredInputRef` records set `materialization` to
`attempt_workspace`. Records without that field use `declared_path`, which
preserves their saved stage-invocation paths during verification.

The [release report](../releases/0.1.0a4.md) lists the Python API and protocol changes
in this candidate.
