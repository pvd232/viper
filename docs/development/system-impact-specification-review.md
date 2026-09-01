# SystemGraph specification-system review

## 1. Reviewed scope

This review covers the SystemGraph slice of the VIPER specification stack on
the working tree based on commit
`1821b8c`:

- [`system-impact-graph.md`](system-impact-graph.md), the concrete contract;
- [`system-impact-compiler.md`](system-impact-compiler.md), the research and
  phase model;
- [`appendix-a-foundations.md`](proof/graph_transformation/appendix-a-foundations.md),
  the formal foundation;
- [`contract-requirement-traceability.md`](contract-requirement-traceability.md),
  the `RuleEdge` declaration contract;
- [`master-execution-checklist.md`](master-execution-checklist.md), the
  authoritative execution order;
- [`system-impact-phase-0-1-pair-coding.md`](system-impact-phase-0-1-pair-coding.md),
  the canonical SystemGraph PairBlocks;
- the historical SystemGraph section of
  [`phase-0-pair-coding.md`](phase-0-pair-coding.md);
- `src/viper/_contract_traceability.py`;
- `tests/test_validation_architecture.py`, `tests/test_public_api.py`,
  `tests/test_documentation.py`, and `tests/test_inspection.py`; and
- `pyproject.toml` and the current package tree.

Reference and archive directories are outside the active design state unless
an active contract links to a specific artifact. The historical SystemGraph
PairBlocks remain readable and are explicitly excluded from the active
PairBlock set by the new guide and documentation validator.

## 2. Mechanical comparison results

The schema gate passes for the reviewed design state.

- The documentation suite parsed all embedded Python and TOML used by the
  active contracts and PairBlocks.
- The SystemGraph contract and PairBlock guide contain the same four node kinds,
  twenty-one dependency-edge kinds, four Phase 0 graph-fact kinds, and three
  target-constraint operators.
- The master checklist contains exactly one implementation and at least one
  verification binding for every SystemGraph verifier rule.
- The checklist's `system-impact-graph.md` baseline equals SHA-256
  `67bcd9150a0cb79b1339b36a4a2ba41cccd7b10148827b63873dc6788e0f9188`.
- Phase 0 checklist markers resolve to the canonical guide for every
  `P0-SIG-*` and `P0-PROOF-09` through `P0-PROOF-12` block. The four Phase 1
  SystemGraph tasks resolve to `P1-SIG-01` through `P1-SIG-04`.
- The current package ends before `src/viper/system_graph.py`. The schema
  comparison therefore establishes the planned model.

Executed check:

```text
/Users/machina/miniconda3/bin/conda run -n mantra \
  python -m pytest tests/test_documentation.py -q
39 passed
```

## 3. Value-lifecycle findings

| Value | Producer | First available | Runtime form | Persisted form | Verifier reconstruction |
| --- | --- | --- | --- | --- | --- |
| `G0` | `compile_system(R0, X)` | after inventory and strict extraction | canonical `SystemGraph` | `graph.json` | recompile the same Git tree and context; compare canonical bytes |
| `RuleEdge` declarations | contract/checklist compiler | after marker parsing | `RuleEdge` tuple | included in contract compilation evidence | reparse declarations; require one owner and at least one test per rule |
| normalized rule dependencies | `lower_rule_edges()` | after target resolution | typed `SystemEdge` values | part of `graph.json` | lower again and compare owner-to-rule and test-to-rule edges |
| contract `Delta` | `compile_contract_delta()` | after parsing and precondition checks | closed typed operation tuple | `delta.json` | reparse the fenced TOML and validate each baseline identity |
| `S_delta` | delta support projection | after delta validation | node-ID set | part of `impact.json` | collect every named baseline endpoint and introduced node |
| `D_delta_plus` | delta edge projection | after delta validation | endpoint-pair set | part of `impact.json` | project every added or replacement dependency edge |
| `H_delta` | `compile_impact_overlay()` | after `G0` and delta compilation | `D0 union D_delta_plus` | `impact.json` evidence | rebuild the union and retain removed baseline edges |
| `B` | `compute_impact()` | after overlay construction | ordered node-ID tuple | `impact.json` | repeat reverse reachability from `S_delta` in `H_delta` |
| SCC condensation | `condense_affected_graph()` | after `B` | components, crossing witnesses, canonical order | `condensation.json` | rerun SCCs on `H_delta[B]`, hash sorted membership, and verify DAG order |
| `P` | `compile_propagation_plan()` | after impact analysis and accepted repair decisions | total typed dispositions and planned additions | `propagation.json` | require one disposition per affected baseline node and one addition per introduced node |
| `T*` | `compile_target_constraints()` | after `(G0, Delta, P)` | canonical `TargetSpecification` over presence, absence, and preservation constraints | `target-constraints.json` | recompile, merge equal predicates and origins, reject contradictions, and compare canonical bytes |
| generated PairBlocks | `compile_work()` | after `T*`, selected repairs, and SCC ordering | bounded work records | `pair-blocks.toml` | require every hard target obligation to be owned once and every block dependency to respect the condensation order |
| selected tests | `select_blast_tests()` | after `B_exec` | ordered pytest node IDs | `blast-coverage.json` | trace each affected executable symbol to at least one test |
| blast execution | pytest-cov and coverage.py | after selected tests run | contexts, statements, and arcs | coverage data plus `blast-coverage.json` | intersect possible and executed statements/arcs with each affected span |
| `G1` | `compile_system(R1, X)` | after implementation | canonical `SystemGraph`, including normalized Python signature facts | candidate `graph.json` | recompile `R1`; compare with `T*` and an optional frozen `G*` projection |
| target conformance | `evaluate_target_conformance()` | after `G1` | one `ConstraintConformanceReceipt` per target constraint | `conformance.json` | reconstruct every Phase 0 graph fact and require `conforms` exactly when all receipts are satisfied |

Every persisted digest covers values available to its verifier in the reviewed
design. The implementation must keep coverage data, context identity, compiler
version, and analyzer registry identity available to verification.

## 4. Requirement-traceability findings

| Requirement | Protocol field | Runtime operation | Persisted evidence | Verifier rule | Acceptance test |
| --- | --- | --- | --- | --- | --- |
| `SIG-01` | node union, stable and planned anchors, normalized Python signatures, `SystemEdge`, `GraphFact`, `FileAnalysisReceipt`, `DependencySiteReceipt` | inventory and Python extraction | graph, receipts, site ledger | node/edge/fact vocabulary, signature canonicality, inventory, anchoring, total analysis, edge evidence | AST oracle parity and dependency-matrix tests in `tests/test_validation_architecture.py` |
| `SIG-02` | `SystemContextManifest`, `SystemDiagnostic`, unresolved outcomes | strict validation and canonical compilation | diagnostics plus graph identity | context, resolution totality, diagnostics, references, canonical bytes, strict rejection | diagnostic golden cases and deterministic recompilation in `tests/test_validation_architecture.py` |
| `SIG-03` | contract delta, impact overlay, SCC condensation, `PropagationPlan`, `TargetSpecification`, conformance receipts | delta compilation, overlay, closure, SCC, propagation, target compilation, conformance | delta, impact, condensation, propagation, target constraints, conformance | delta validity, conservative overlay, closure, SCC membership/order, total disposition, target-language closure, canonical target compilation, total conformance | local-store and manifest-rename replays in `tests/test_inspection.py` |
| `SIG-04` | requirements, verifier rules, `RuleEdge`, PairBlock, `BlastCoverageReport` | contract compiler, rule lowering, test selection, coverage verification | traceability graph and blast report | requirement/rule/plan coverage plus selected-test, statement, and branch coverage | contract mutation tests in `tests/test_documentation.py` and blast mutants in `tests/test_inspection.py` |

Every requirement has a planned runtime owner and named acceptance test. The
first unimplemented connector is `src/viper/system_graph.py:SystemNode`; the
Phase 0 checklist and `P0-SIG-01` own that expected implementation lag.

## 5. Counterexamples

### Vocabulary and extraction

Initial plan: compile a file containing `from storage import Store` and a call
to `Store()`. Mutation: omit the call-site receipt and `constructs` edge. False
result: the inventory remains complete while the blast misses constructor
dependents. `system.analysis.total` and the AST-oracle mutant reject the graph.

### Contract compilation

Initial plan: remove one import edge while a separate call dependency remains.
Mutation: project `RuleEdge` or contract operations directly in their declared
direction. False result: reverse traversal walks from the rule toward the owner
and misses the owner as a dependent. `system.rule.lowering` rejects the edge
direction and recomputes `owner -> rule` or `test -> rule`.

### Conservative overlay

Initial plan: remove `api -> storage` while changing storage's contract.
Mutation: subtract the removed baseline edge before impact analysis. False
result: `api` disappears from the blast before migration work is considered.
`system.impact.overlay` rebuilds `D0 union D_delta_plus` and retains the
baseline pair.

### SCC condensation

Initial plan: affected symbols `a` and `b` depend on each other. Mutation:
topologically sort the raw affected graph or split the two symbols between work
owners. False result: scheduling either symbol first violates a dependency.
`system.dag.components` places both in one atomic SCC and
`system.dag.acyclic` checks the condensation.

### Target compilation

Initial plan: one delta operation requires a node while a propagation
disposition forbids the same node. Mutation: emit both predicates into `T*`
and leave resolution to the implementation agent. False result: no repository
can satisfy the target. `system.target.canonical` rejects the contradiction
before PairBlock generation.

Initial plan: two obligations require the same edge for different reasons.
Mutation: emit two independently identified constraints. False result: target
identity depends on input ordering and conformance can produce duplicate
receipts. Canonical compilation merges the origins under one predicate and
derives its identifier from the normalized predicate.

### Blast coverage

Initial plan: a selected test executes the true branch of an affected
condition. Mutation: accept 100 percent statement coverage while the false arc
remains unexecuted. False result: the phase closes while leaving one
affected behavior. `system.blast.branch_coverage` rejects the missing arc.

### Conformance

Initial plan: `T*` permits two valid storage implementations. Mutation: require
raw equality with one unfrozen `G*`. False result: a conforming alternative is
rejected. Conformance checks `G1 models T*`; graph equality is used only when a
PairBlock explicitly freezes the relevant construction.

## 6. Propagation discrepancies

| Surface | Prior discrepancy | Disposition |
| --- | --- | --- |
| `system-impact-graph.md` | Treated a two-revision diff as the normative delta and implied that the delta determined the future graph | Repaired: the contract delta precedes implementation; `(G0, Delta, P)` determines target constraints; observed `G1` supplies conformance evidence |
| `system-impact-graph.md` | Mixed dependency edges with descriptive and inverse relationships | Repaired: every edge means source depends on target; descriptive data moved outside `E` |
| `RuleEdge` | Declaration direction ran from rule to target | Repaired: `RuleEdge` remains a declaration and lowers mechanically to owner/test-to-rule dependencies |
| extraction coverage | One file receipt could appear complete while dependency sites were omitted | Repaired: every registered AST site receives a terminal receipt; mutation tests kill omitted edges and receipts |
| impact graph | Removed edges could disappear before migration impact was computed | Repaired: `H_delta` retains `D0` and adds introduced dependencies |
| cycle handling | SCC scope and canonical ordering were underspecified | Repaired: iterative Tarjan runs on `H_delta[B]`; SCCs are atomic; crossing witnesses and deterministic Kahn order are required |
| test completeness | “Reached tests” established a graph path only | Repaired: selected tests must cover every affected statement and branch arc with per-test contexts |
| target language | `T*` was named without an executable closed schema | Repaired: four Phase 0 graph facts combine with presence, absence, and preservation; compilation merges equal predicates and rejects contradictions |
| PairBlock lifecycle | Contract compilation appeared to consume human-authored PairBlocks | Repaired: contract declarations produce `Delta`; accepted decisions produce `P`; `(G0, Delta, P)` produces `T*`; `compile_work()` then packages selected repairs into SCC-ordered PairBlocks |
| `phase-0-pair-coding.md` | Embedded SystemGraph blocks contain the superseded model | Classified as historical and excluded from the active PairBlock validator; Phase 0 removes the section after oracle parity |
| source package | `src/viper/system_graph.py` is absent | Planned implementation lag owned by `P0-SIG-01` through `P0-SIG-11` |
| test dependencies | coverage.py and pytest-cov are absent from the test extra | Planned change owned by `P0-SIG-10`; dependency addition occurs in its implementation block |

The canonical guide and validator routing align every active SystemGraph
specification. The historical block is visibly marked and mechanically
excluded.

## 7. Status decision for each contract

| Artifact | State | Decision |
| --- | --- | --- |
| `system-impact-graph.md` | Audited | All five design gates pass; owner approval and implementation remain pending |
| `system-impact-phase-0-1-pair-coding.md` | Audited | The active PairBlocks cover Phase 0 and the bounded Phase 1 extensions with explicit dependencies and gates |
| SystemGraph slice of `master-execution-checklist.md` | Audited | Requirement ownership, execution order, evidence, tests, kill gate, and Phase 1 boundary are explicit |
| formal appendix and `system-impact-compiler.md` | Audited inputs | The concrete contract preserves the formal correction that `Delta` alone underdetermines a complete future graph |
| historical SystemGraph section in `phase-0-pair-coding.md` | Draft, non-authoritative | Retained only as a migration oracle and scheduled for removal after parity |
| SystemGraph implementation | Draft | The module, runtime compiler, persisted artifacts, and acceptance tests remain planned |

The reviewed design is ready for owner approval and bounded Phase 0
implementation. The SystemGraph contract remains `Audited`.

## 8. Exact validation results

The isolated task snapshot passed:

```text
/Users/machina/miniconda3/bin/conda run -n mantra \
  python -m pytest \
  tests/test_documentation.py \
  tests/test_validation_architecture.py \
  tests/test_public_api.py \
  tests/test_inspection.py -q
60 passed

/Users/machina/miniconda3/bin/conda run -n mantra \
  python -m ruff check tests/test_documentation.py
All checks passed

git diff --check
passed
```

The direct-prose advisory checker reports 38 findings across the formal
contract and appendix, mostly mathematical negations required to state absence,
non-conformance, and proof conditions. The repository's mechanical prose gate
does not consume that advisory result.
