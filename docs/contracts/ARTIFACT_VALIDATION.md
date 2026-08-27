# Artifact validation

## Status

Exact loader references, complete bundle checks, worker-owned loader
invocation, named guarantee results, and terminal resume parity are
implemented.

## Required claim

VIPER reports the strongest artifact guarantee established by the available
evidence: representation identity, loadability, or reserved semantic validity.

## Implemented path

[`verify_snapshot_artifact()`](../../src/viper/verifier.py) verifies every resolved
file. [`load_verified_artifact()`](../../src/viper/verifier.py) invokes the declared
loader and returns its value. The same function applies `ResumeState` validation
only when the artifact name is `resume_state`.

Generic loader success establishes loadability after byte verification.
Reserved artifact names invoke protocol-owned semantic validators when the
protocol defines an expected value.

## Contract models

```python
class ArtifactLoaderRef(ProtocolModel):
    path: PythonRepoRelPath
    symbol: PythonSymbol = "load"
    sha256: SHA256
    bytes: int = Field(gt=0)
```

`ArtifactSpec.loader` uses this reference. Reserved artifact names select
protocol-owned validators. Generic artifacts receive the loadability check.

## Execution

Stage publication enumerates every regular file beneath a bundle root, rejects
symlinks, and records each relative member path, digest, and byte count. The
verifier materializes exactly that file set before loader invocation.

## Persisted evidence

Single-file artifacts store one file identity. Bundle artifacts store the
complete ordered member list. The stage snapshot fixes the resolved spec and
the represented files in one immutable revision.

## Verification

| Check | Rule |
|---|---|
| `artifact.representation` | Every persisted byte matches its recorded path, SHA-256, and byte count. |
| `artifact.bundle` | The resolved member list is unique, contained, and complete for the published bundle root. |
| `artifact.loader` | The loader bytes and symbol match `ArtifactLoaderRef`. |
| `artifact.loadability` | The loader accepts the complete verified representation. |
| `artifact.semantic.resume_state` | The loaded value validates as `ResumeState`. |

Bundle minimality remains an authoring decision based on actual consumer needs.

## Propagation

| Surface | Implemented mechanism |
|---|---|
| Protocol | `ArtifactLoaderRef` fixes loader identity. |
| Stage publication | Complete bundle enumeration fixes every member. |
| Worker | A dedicated trusted-local worker invokes the selected loader. |
| Verification | Separate checks establish representation, loadability, and semantic validity. |
| Errors | Each failure names its guarantee level. |
| Tests | Generic loadability, reserved semantic validation, same-length tampering, missing members, and extra members exercise the contract. |

## Acceptance case

A bundle contains `config.json` and `weights.safetensors`. Publication records
both files. The frozen loader accepts the materialized directory, so
`artifact.loadability` passes.

The rejection case replaces one member with different bytes of the same
length. `artifact.representation` fails on SHA-256.

## Completed implementation sequence

1. Add `ArtifactLoaderRef` and migrate authored specs.
2. Align verifier results and errors with the three guarantee levels.
3. Invoke loaders through the execution backend.
4. Add focused bundle and semantic-validation tests.
5. Update the protocol language.
