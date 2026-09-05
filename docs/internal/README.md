# VIPER internal engineering

This directory is the doorway from reader documentation into VIPER's
development system. The linked documents govern implementation, verification,
release work, and future research. They are not user tutorials.

## Execute approved work

| Document | Purpose |
| --- | --- |
| [Master execution checklist](../development/master-execution-checklist.md) | Orders approved contract work and records completion evidence. |
| [Contract traceability](../development/contract-traceability.md) | Connects requirements, PairBlocks, implementation owners, and tests. |
| [System Impact Check](../development/system-impact-compiler.md) | Checks planned source changes against baseline and candidate source graphs. |
| [PairBlock scheduling](../development/pair-block-scheduling.md) | Orders or parallelizes PairBlocks from explicit dependencies and source impact. |
| [Documentation architecture](../development/documentation-architecture.md) | Keeps user learning, reference, and internal engineering routes distinct. |

## Product contracts

The implementation contracts remain in `docs/development/` because their
paths, digests, PairBlock IDs, and compiler fixtures are executable authority.
Use the master checklist to enter them in dependency order. Do not copy their
code specifications into reader documentation.

## Maintainer guides

- [Testing](../development/testing.md)
- [CodeQL analysis](../development/codeql-analysis.md)
- [Child-process launching](../development/child-process-launching.md)
- [Module ownership](../development/module-ownership.md)
- [Module privacy](../development/module-privacy.md)
- [Archived foundational reproducibility formalism](foundational-reproducibility-formalism.md)

## Release evidence

- [0.1.0a2](../releases/0.1.0a2.md)
- [0.1.0a1](../releases/0.1.0a1.md)

Research plans remain under `docs/development/` until they become approved
contracts or move to a dedicated research archive.
