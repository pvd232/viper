# VIPER workday journal — 2026-08-31

This entry covers the continuous August 31 workday through the final overnight
commit at 03:23 ET on September 1.

## Day charter

The day established a deterministic foundation for Master Phase 0: stable
public ownership, an executable project-root plan, contract traceability, and
one proof-backed System Impact Compiler specification ready for implementation.

## Completed today

### Public ownership and repository foundation

- Moved public API and verification imports to their defining modules, removed
  redundant aliases and pass-through ownership, and aligned the reference,
  tutorial, explanation, protocol, and test surfaces with those owners.
- Added enforcement for public-module ownership and documented the remaining
  module migration as exact `P0-MOD` PairBlocks.
- Defined the project-root implementation sequence around `ProjectSettings`,
  `resolve_project_root()`, the `viper.toml` marker, the staged protocol tree,
  path containment, and `LocalArtifactStore`. The guide and checklist are
  executable; the unchecked `P0-PDR` blocks still represent pending production
  implementation.

### Contract traceability

- Added the initial `ContractTraceabilityGraph` model safeguards and the
  documentation checks that protect requirement, rule, owner, test, source
  span, model, example, and diagram structure.
- Produced the complete [Contract Traceability Pair-Coding
  Guide](../docs/development/contract-traceability-pair-coding.md), including
  production blocks `P0-CRT-01` through `P0-CRT-05` and their acceptance
  blocks.
- Fixed the compiler boundary: `compile_contract_traceability()` derives
  `ContractTraceabilityGraph` from the selected repository, while
  `compile_system()` lowers that graph with source facts and bootstrap
  PairBlocks into `SystemGraph`. `compile_contract_change()` then resolves one
  `ContractChange` against `G0` and emits `ContractDelta`.

### System Impact Compiler and proof

- Formalized the complete protocol from baseline compilation through observed
  conformance: `R0 -> G0 -> ContractDelta -> ImpactReport -> PropagationPlan ->
  TargetSpecification -> PairBlocks -> R1 -> G1`.
- Proved graph-relative minimality, conservative blast-radius soundness under
  the compiler-soundness assumption, total propagation-plan coverage,
  deterministic target derivation under frozen inputs, and the limits of
  structural conformance.
- Preserved the central correction: a complete future graph requires both
  `ContractDelta` and `PropagationPlan`. `PropagationPlan` supplies required
  treatment of the affected nodes, and `TargetSpecification` defines the
  admissible future graphs before repair selection freezes a particular
  structure.
- Unified the proof, requirements, implementation contracts, diagnostics,
  verification rules, PairBlocks, worked five-file example, literature, and
  checklist ties in the [System Impact Compiler
  specification](../docs/development/system-impact-compiler.md). The unified
  specification replaces the retired SystemGraph drafts and split proof
  documents as the source of truth.
- Restored the full integrated dependency DAG and added a compact top-to-bottom
  Mermaid overview. Both diagrams retain the separate source-analysis,
  contract, change, impact, planning, execution, observation, and acceptance
  paths.

### CodeQL-backed source analysis

- Set the production architecture: CodeQL extracts and queries source facts at
  `R0` and `R1`; VIPER owns `SystemGraph`, `ContractDelta`, impact semantics,
  `PropagationPlan`, `TargetSpecification`, PairBlock compilation, and the
  acceptance decision.
- Pinned CodeQL CLI `2.26.4` as the Master Phase 0 review baseline and specified
  `CodeQLPackIdentity`, `CodeQLToolchainIdentity`,
  `SystemCompilerIdentity`, `CodeQLDatabaseReceipt`,
  `CodeQLAnalysisReceipt`, `CodeQLSourceFacts`, and stable result schemas.
- Defined the Phase 0 extraction matrix, dependency-site receipts, stable
  diagnostic families, and global rejection of unresolved or unsupported
  dependency sites before blast-radius computation.
- Assigned reverse reachability and mutual-reachability queries to the locked
  VIPER QL pack. The existing AST checks and an independent Tarjan
  implementation remain verification oracles.
- Specified complete statement and branch coverage for every executable symbol
  in the blast radius, with pytest node IDs and coverage contexts carried in a
  `BlastCoverageReport`.
- Converted the implementation into dependency-ordered blocks `P0-SIG-01`
  through `P0-SIG-11`, plus the focused proof blocks that establish CodeQL
  parity and system-level guarantees.

### Checklist, naming, and validation

- Standardized scheduled work as `Master Phase N` and stable work units as
  `P0-CRT-*`, `P0-PDR-*`, `P0-MOD-*`, `P0-SIG-*`, and `P0-PROOF-*`.
- Reconciled the [Master Execution
  Checklist](../docs/development/master-execution-checklist.md), contract
  guides, test strategy, CI paths, and documentation tests with the final
  architecture.
- Published 29 task-scoped commits during the workday. The final commit was
  `8934d92` (`Specify CodeQL-backed system impact compiler`), and `main` matched
  `origin/main` at shutdown.
- Final validation completed with 278 tests passed, 6 skipped, and 29 subtests
  passed. The focused System Impact run passed 56 tests; the final
  documentation run passed 47 tests; Ruff, formatting, Mermaid rendering in
  light and dark themes, prose checks for the new material, and Git whitespace
  checks also passed.

## Capacity for 2026-09-01

Assumption: one seven-hour focused session with six hours assigned to planned
work and one hour reserved for debugging, breaks, and handoff. The assumed
session ends after seven hours. The primary outcome is a complete, tested
`P0-SIG-01`; the secondary outcome is the first independently testable
`P0-SIG-02` CodeQL database receipt.

## Execution plan for 2026-09-01

| Elapsed budget | Work block | Deliverable | Done condition |
| --- | --- | --- | --- |
| 0:00–0:20 | Reopen the exact `P0-SIG-01` block and verify the repository and `mantra` environment | A bounded edit set for `src/viper/system_graph.py` and `tests/test_validation_architecture.py` | The worktree is synchronized, the runtime resolves to the `mantra` interpreter, and the two named acceptance tests are the active gate. |
| 0:20–2:50 | Implement `P0-SIG-01` | Public graph, anchor, signature, CodeQL fact and receipt, diagnostic, target-constraint, and conformance models with canonical ID helpers | Every model and closed vocabulary named by `P0-SIG-01` exists under its specified implementation name and rejects invalid combinations deterministically. |
| 2:50–4:10 | Implement and run the `P0-SIG-01` acceptance tests | Table-driven coverage in `tests/test_validation_architecture.py` | `test_system_graph_vocabulary_is_closed` and `test_system_target_language_is_closed` pass under the documented focused gate. |
| 4:10–5:25 | Start `P0-SIG-02` at the external-tool boundary | Verified CodeQL CLI `2.26.4` identity, repository inventory, private `create_codeql_database()` adapter, and `CodeQLDatabaseReceipt` for the selected commit | `test_codeql_database_receipt_binds_source_and_toolchain` passes. Treat the CodeQL install and database build time as uncertain; stop after the receipt boundary. |
| 5:25–6:00 | Inspect, document, and publish the completed increment | Task-scoped commit, checklist state update for completed blocks only, and exact next-block handoff | The selected tests and Git whitespace check pass, the commit is pushed, and local `HEAD` matches `origin/main`. |
| 6:00–7:00 | Reserved slack | Recovery time for model-validation defects, CodeQL setup, transitions, and short breaks | Use only for overruns in the blocks above; leave unused time unassigned. |

## Replan rule

If either `P0-SIG-01` acceptance test still fails at elapsed hour 4:10, defer
all `P0-SIG-02` work. Use the remaining planned time to close the public model
vocabulary, diagnostics, canonicalization rules, and focused tests, then
publish `P0-SIG-01` as the complete increment.

## Deferred from 2026-09-01

- `P0-SIG-03` source-fact QL queries and BQRS lowering.
- `P0-SIG-04` contract and PairBlock ingestion.
- Blast-radius computation, SCC condensation, propagation planning, target
  compilation, blast coverage, and post-implementation conformance.
- Dynamic-dispatch recovery, runtime observations, or Master Phase 1 model
  packs.
- Unrelated project-root, publication, storage, metric, experiment, MCP, or
  release implementation.

## Shutdown

The 8/31 workday ended with the architecture, proof, nomenclature, checklist,
and CodeQL implementation contract synchronized on `main`. Production work
remains open across Master Phase 0. The next session starts at
`P0-SIG-01`: open Section 14.3 of the System Impact Compiler specification and
implement the named public types in `src/viper/system_graph.py` before touching
the CodeQL adapter.
