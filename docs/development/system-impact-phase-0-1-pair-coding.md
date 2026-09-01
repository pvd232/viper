# SystemGraph Phase 0 and Phase 1 pair-coding guide

This is the canonical implementation sequence for the SystemGraph compiler.
It replaces the SystemGraph blocks embedded in
[`phase-0-pair-coding.md`](phase-0-pair-coding.md). The older blocks remain a
historical draft until Phase 0 removes them.

## 1. Status and boundary

**Guide status:** working-tree contract correction based on commit
`9868783`; implementation pending.

Phase 0 must produce one strict, deterministic path:

```text
R0 + X + canonical ContractTraceabilityGraph + bootstrap PairBlocks
-> G0 with normalized rule and scheduling dependencies
explicit contract-delta declaration + G0
-> Delta
-> S_delta + D_delta_plus
-> H_delta
-> B
-> SCC(H_delta[B])
-> condensation DAG
-> selected tests
-> complete statement and branch execution over B_exec
-> total propagation plan P
-> target constraints T*
-> selected repair operations
-> generated PairBlocks
```

After implementation:

```text
R1 + X -> G1
G1 models T*
```

`Delta` generally underdetermines the complete future graph. An accepted
propagation plan provides the required, forbidden, and preserved graph facts
for every affected surface. `(G0, Delta, P)` compiles the target constraints.
`CompileWork` packages selected repair operations and those constraints as
ordered PairBlocks.

The blocks in this guide are bootstrap PairBlocks: humans authored them to
implement the compiler before `CompileWork` exists. Production impact analysis
does not read them to derive `Delta`, `S_delta`, or `H_delta`.

Phase 1 adds the smallest high-return extensions: observed dynamic resolution,
configuration and Markdown analyzers, persisted artifacts and developer
commands, and SCC-safe workload metrics. Learned ranking, exhaustive repair
search, and optimized multi-agent partitioning remain later work.

## 2. Locked vocabulary

### SystemNode set

The implementation uses a discriminated node union whose variants carry their
own required fields.

| Kind | Stable ID | Required evidence |
| --- | --- | --- |
| `repository_file` | `file:<path>` | Git path, byte count, complete-file SHA-256 |
| `python_symbol` | `python:<path>:<qualified-name>` | declaration kind, four AST coordinates, exact-span SHA-256 |
| `document_anchor` | `anchor:<path>:<anchor-kind>:<stable-id>` | marker kind, stable ID, line range, exact-span SHA-256 |
| `external_symbol` | `external:<external-kind>:<context-identity>` | external kind and identity present in `SystemContextManifest` |

The finite role vocabulary and compatibility matrix live in
[`system-impact-graph.md`](system-impact-graph.md#identifiers-and-kinds). A
validator recomputes every ID and rejects an inadmissible role-kind pair.

### SystemEdge set

Every `SystemEdge` means `source depends on target`. Phase 0 accepts only:

```text
contained_by
imports_module       imports_symbol
calls                constructs
inherits_from        uses_type
reads_symbol         writes_symbol
decorated_by         registers_with
exports_symbol
declared_by          implements_rule       verifies_rule
scheduled_by         targets               gated_by
block_depends_on
reads_context        launches
```

The edge identity hashes source, kind, target, origin, and evidence. Node
attributes, evidence, and reports carry descriptive relationships.

### RuleEdge set

`RuleEdgeKind` remains exactly `implementation | verification`. `RuleEdge`
serves as a parsed declaration whose lowered result enters the dependency
graph. The compiler requires exactly one
implementation binding and at least one verification binding for every
`VerifierRule`, then lowers the declarations as follows:

```text
implementation binding(rule, owner) -> owner --implements_rule--> rule
verification binding(rule, test)    -> test  --verifies_rule----> rule
```

This inversion is required because the stored dependency direction is
dependent to dependency.

### Target-constraint set

VIPER uses three local atomic constraint operators:

```text
presence       the fact must occur in G1
absence        the fact must not occur in G1
preservation   the fact projected from G0 must occur unchanged in G1
```

The Phase 0 `GraphFact` union contains exactly:

```text
node_identity
node_roles
python_signature
edge
```

These Python names are VIPER conventions. Algebraic graph transformation
supplies the established graph-constraint and satisfaction semantics; it does
not prescribe these class names.

`SystemNodeAnchor` carries stable identity fields without observed source
evidence. `PlannedNodeAnchor` identifies one future node and the delta
operation that introduced it. `SystemNode` carries the coordinates and digest
observed after repository compilation.

## 3. Phase 0 diagnostics contract

Every diagnostic contains `code`, `severity`, `phase`, exact source location
when available, related node and edge IDs, a concrete message, and remediation.
Tests assert the stable code and structured fields.

| Code | Trigger | Strict result |
| --- | --- | --- |
| `SGI001` | tracked file lacks an analysis receipt | reject |
| `SGI002` | inventory or receipt digest mismatch | reject |
| `SGI003` | behavior-bearing tracked file is opaque or excluded | reject |
| `SGX001` | Python parse failure | reject |
| `SGX002` | registered AST dependency site lacks a receipt | reject |
| `SGX003` | unresolved import or name | reject when in `B` |
| `SGX004` | dynamic call, star import, or computed registry target is unsupported | reject when in `B` |
| `SGC001` | malformed or duplicate contract declaration | reject |
| `SGC002` | unknown requirement, rule, target, test, or PairBlock | reject |
| `SGC003` | verifier rule lacks one owner or any observing test | reject |
| `SGC004` | delta precondition is stale or operations conflict | reject |
| `SGG001` | node ID, role, or required field is invalid | reject |
| `SGG002` | edge endpoint, direction, kind, evidence, or ID is invalid | reject |
| `SGG003` | canonical ordering or repeated compilation differs | reject |
| `SGB001` | affected executable node lacks a selected test | reject |
| `SGB002` | unexecuted affected statement | reject |
| `SGB003` | unexecuted affected branch arc | reject |
| `SGS001` | SCC membership or component identity differs | reject |
| `SGS002` | crossing-edge witnesses differ or condensation remains cyclic | reject |

Exploratory mode may serialize unresolved diagnostics. Complete impact,
coverage, and implementation-gate outputs require strict mode.

## 4. Phase 0 PairBlocks

Each turn implements one block, runs its focused gate, and stops for inspection.

<!-- pair-block-definition: P0-SIG-01 -->
```toml pair-block
id = "P0-SIG-01"
requirements = ["SIG-01", "SIG-02"]
targets = ["src/viper/system_graph.py:SystemNode", "src/viper/system_graph.py:SystemNodeAnchor", "src/viper/system_graph.py:PlannedNodeAnchor", "src/viper/system_graph.py:SystemEdge", "src/viper/system_graph.py:GraphFact", "src/viper/system_graph.py:TargetConstraint", "src/viper/system_graph.py:TargetSpecification", "src/viper/system_graph.py:ConstraintConformanceReceipt", "src/viper/system_graph.py:SystemDiagnostic"]
tests = ["tests/test_validation_architecture.py:test_system_graph_vocabulary_is_closed", "tests/test_validation_architecture.py:test_system_target_language_is_closed"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k 'system_graph_vocabulary_is_closed or system_target_language_is_closed' -q"
depends_on = []
```

Add the four node variants, finite roles, canonical dependency kinds, evidence
variants, dependency-site receipts, diagnostics, stable anchors, four graph
fact variants, three target operators, normalized Python signatures, target
specification, conformance receipts, and canonical ID helpers. Write
table-driven failures for every invalid kind-field, role-kind, fact-constraint,
and signature combination.

<!-- pair-block-definition: P0-SIG-02 -->
```toml pair-block
id = "P0-SIG-02"
requirements = ["SIG-01"]
targets = ["src/viper/system_graph.py:inventory_repository", "src/viper/system_graph.py:analyze_python"]
tests = ["tests/test_validation_architecture.py:test_system_graph_inventory_and_sites_are_total"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_inventory_and_sites_are_total -q"
depends_on = ["P0-SIG-01"]
```

Enumerate the selected Git tree, hash exact bytes, and emit one receipt per
file. Move the existing AST parsing pattern from
`tests/test_validation_architecture.py` behind `analyze_python()`. Combine AST
coordinates with `symtable` scope information. Emit one
`DependencySiteReceipt` for every registered site.

<!-- pair-block-definition: P0-SIG-03 -->
```toml pair-block
id = "P0-SIG-03"
requirements = ["SIG-01"]
targets = ["src/viper/system_graph.py:extract_python_dependencies"]
tests = ["tests/test_validation_architecture.py:test_python_dependency_matrix_is_complete"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k python_dependency_matrix_is_complete -q"
depends_on = ["P0-SIG-02"]
```

Implement the Phase 0 extraction matrix:

| Python site | Required result |
| --- | --- |
| `Import`, `ImportFrom` | module or symbol edge with alias and relative level resolved |
| direct `Call` | `calls` or `constructs`; unresolved computed target emits `SGX004` |
| class bases | `inherits_from` |
| decorators | `decorated_by`; known registry decorators also emit `registers_with` |
| annotations | `uses_type`, including postponed annotations |
| `Name` and resolvable `Attribute` loads/stores | `reads_symbol` or `writes_symbol` |
| `__all__` and package re-exports | `exports_symbol` |
| local literal confined to its owning symbol | `self_contained` receipt |
| star import or computed import/registry target | unresolved receipt and diagnostic |

The fixture matrix covers absolute and relative imports, aliases, nested
scopes, closures, class methods, decorators, annotations, registries, exports,
star imports, `importlib.import_module`, and an intentionally unresolved target.

<!-- pair-block-definition: P0-SIG-04 -->
```toml pair-block
id = "P0-SIG-04"
requirements = ["SIG-03", "SIG-04"]
targets = ["src/viper/system_graph.py:ingest_contract_traceability", "src/viper/system_graph.py:compile_pair_blocks", "src/viper/system_graph.py:ingest_pair_blocks", "src/viper/system_graph.py:compile_contract_delta"]
tests = ["tests/test_documentation.py:test_system_graph_preserves_contract_traceability", "tests/test_documentation.py:test_contract_delta_compiles_against_g0", "tests/test_documentation.py:test_phase_zero_checkboxes_have_complete_ordered_pair_blocks"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k 'system_graph_preserves_contract_traceability or contract_delta_compiles_against_g0 or complete_ordered_pair_blocks' -q"
depends_on = ["P0-CRT-05", "P0-SIG-03"]
```

Consume the canonical `ContractTraceabilityGraph` produced by `P0-CRT-05`.
Lower its source-evidenced requirement, rule, owner, and test bindings into
baseline nodes and dependencies while compiling `G0`; do not parse those
declarations again. Parse bootstrap PairBlocks separately and lower their work
traceability into `G0`.

After `G0` exists, parse the fenced `contract-delta` TOML and resolve each
baseline anchor against `G0` or each addition against an explicit
`PlannedNodeAnchor`. Reject unknown anchors, stale digests, duplicate or
conflicting operations, and invalid application order. This stage emits
`ContractDelta`; `P0-SIG-05` derives `S_delta`, `D_delta_plus`, and the impact
overlay.

<!-- pair-block-definition: P0-SIG-05 -->
```toml pair-block
id = "P0-SIG-05"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:compile_impact_overlay"]
tests = ["tests/test_inspection.py:test_contract_delta_builds_conservative_overlay"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k contract_delta_builds_conservative_overlay -q"
depends_on = ["P0-SIG-03", "P0-SIG-04"]
```

Project every typed edge in `G0` to `D0`, derive `S_delta` and
`D_delta_plus`, and build `D_H_delta = D0 union D_delta_plus`. A removal fixture
must prove that the removed baseline pair remains in the overlay. An introduced
node and edge fixture must prove that both enter the overlay.

<!-- pair-block-definition: P0-SIG-06 -->
```toml pair-block
id = "P0-SIG-06"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:compute_impact"]
tests = ["tests/test_inspection.py:test_reverse_impact_is_least_predecessor_closed_superset"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k least_predecessor_closed_superset -q"
depends_on = ["P0-SIG-05"]
```

Compute reverse reachability from `S_delta` in `H_delta`. The test checks seed
inclusion, predecessor closure, minimality against enumerated closed supersets
in small graphs, introduced vertices, removed edges, self-reachability, and one
mutant with an omitted semantic dependency.

<!-- pair-block-definition: P0-SIG-07 -->
```toml pair-block
id = "P0-SIG-07"
requirements = ["SIG-02"]
targets = ["src/viper/system_graph.py:validate_strict_impact"]
tests = ["tests/test_validation_architecture.py:test_system_graph_diagnostics_fail_closed"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_diagnostics_fail_closed -q"
depends_on = ["P0-SIG-05", "P0-SIG-06"]
```

Collect diagnostics across the complete file set. Sort by code, path, line, and
diagnostic ID. Strict validation rejects any error and specifically
rejects unresolved or unsupported dependency sites reached by `B`. Golden
tests assert every Phase 0 diagnostic code and its fields.

<!-- pair-block-definition: P0-SIG-08 -->
```toml pair-block
id = "P0-SIG-08"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:strongly_connected_components", "src/viper/system_graph.py:condense_affected_graph"]
tests = ["tests/test_inspection.py:test_affected_graph_condensation_is_canonical"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k affected_graph_condensation_is_canonical -q"
depends_on = ["P0-SIG-06"]
```

Run iterative Tarjan on `H_delta[B]` with sorted vertices and adjacency. Hash
sorted component members, preserve typed crossing-edge witnesses, mark
multi-member and self-loop components as cyclic, and apply deterministic Kahn
ordering. Test an import cycle, call cycle, self-loop, disconnected component,
parallel crossing edge, shuffled input order, and a mutant that drops one SCC
member.

<!-- pair-block-definition: P0-SIG-09 -->
```toml pair-block
id = "P0-SIG-09"
requirements = ["SIG-03", "SIG-04"]
targets = ["src/viper/system_graph.py:compile_propagation_plan", "src/viper/system_graph.py:compile_target_constraints", "src/viper/system_graph.py:compile_work"]
tests = ["tests/test_inspection.py:test_propagation_plan_is_total", "tests/test_inspection.py:test_target_compilation_is_canonical"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k 'propagation_plan_is_total or target_compilation_is_canonical' -q"
depends_on = ["P0-SIG-06", "P0-SIG-08"]
```

Require one disposition for each baseline affected node and one planned-addition
record for each introduced node. Each disposition supplies typed required,
forbidden, and preserved facts. Compile `T* = CompileTarget(G0, Delta, P)`,
reject contradictory constraints, and merge identical constraints with all
origins. Preserve alternative admissible implementations unless repair
selection freezes one choice. `compile_work()` packages selected repairs and
hard constraints into SCC-ordered PairBlocks.

<!-- pair-block-definition: P0-SIG-10 -->
```toml pair-block
id = "P0-SIG-10"
requirements = ["SIG-04"]
targets = ["src/viper/system_graph.py:select_blast_tests", "src/viper/system_graph.py:verify_blast_coverage"]
tests = ["tests/test_inspection.py:test_selected_tests_cover_the_executable_blast"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k selected_tests_cover_the_executable_blast -q"
depends_on = ["P0-SIG-06", "P0-SIG-07"]
```

Select pytest node IDs reached from each executable affected symbol. Run those
tests with branch measurement and per-test contexts. Intersect coverage.py
statements and possible arcs with each affected symbol span. Require zero
missing statements, zero missing arcs, and at least one test context per symbol.
Add `coverage` and `pytest-cov` to the test extra in this block.

<!-- pair-block-definition: P0-SIG-11 -->
```toml pair-block
id = "P0-SIG-11"
requirements = ["SIG-01", "SIG-02", "SIG-03", "SIG-04"]
targets = ["src/viper/system_graph.py:compile_system_change", "src/viper/system_graph.py:evaluate_target_conformance"]
tests = ["tests/test_inspection.py:test_system_change_compilation_is_deterministic", "tests/test_inspection.py:test_target_conformance_is_total"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py tests/test_inspection.py tests/test_documentation.py -k 'system_graph or contract_compiler or target or blast or condensation' -q"
depends_on = ["P0-SIG-07", "P0-SIG-08", "P0-SIG-09", "P0-SIG-10"]
```

Orchestrate Phase 0 and serialize `graph.json`, `delta.json`, `impact.json`,
`diagnostics.json`, `condensation.json`, `propagation.json`,
`target-constraints.json`, and `blast-coverage.json` with canonical JSON. Compile
twice from shuffled input order and require byte equality. Recompile `R1` under
the same context and emit exactly one satisfied, violated, or unevaluable
receipt per target constraint. Strict conformance accepts only all-satisfied
reports.

## 5. Phase 0 proof blocks

<!-- pair-block-definition: P0-PROOF-09 -->
```toml pair-block
id = "P0-PROOF-09"
requirements = ["SIG-01", "SIG-02"]
targets = ["tests/test_validation_architecture.py:test_system_graph_ast_oracle_parity", "tests/test_validation_architecture.py:test_system_target_language_is_closed"]
tests = ["tests/test_validation_architecture.py:test_system_graph_ast_oracle_parity", "tests/test_validation_architecture.py:test_system_target_language_is_closed"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k 'system_graph_ast_oracle_parity or system_target_language_is_closed' -q"
depends_on = ["P0-SIG-03", "P0-SIG-07"]
```

Compare the production analyzer with the existing import/privacy AST oracle.
Delete each expected emitted edge in turn and require the parity or total-site
gate to fail. Mutate each anchor, signature, graph-fact, and target-constraint
variant and require the closed-vocabulary test to reject it.

<!-- pair-block-definition: P0-PROOF-10 -->
```toml pair-block
id = "P0-PROOF-10"
requirements = ["SIG-03"]
targets = ["tests/test_inspection.py:test_system_impact_replays_committed_changes", "tests/test_inspection.py:test_target_compilation_is_canonical", "tests/test_inspection.py:test_target_conformance_is_total"]
tests = ["tests/test_inspection.py:test_system_impact_replays_committed_changes", "tests/test_inspection.py:test_target_compilation_is_canonical", "tests/test_inspection.py:test_target_conformance_is_total"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k 'system_impact_replays_committed_changes or target_compilation_is_canonical or target_conformance_is_total' -q"
depends_on = ["P0-SIG-09", "P0-SIG-11"]
```

Replay the local-store fixture and the fixed skill-manifest rename. Compare the
computed affected paths with the reviewed path sets. Record and justify every
extra path through source evidence; fail on any missing path. Translate every
delta and disposition fact, reject one presence/absence contradiction, shuffle
input order, and require canonical target bytes. Mutate one observed fact and
require exactly one violated conformance receipt.

<!-- pair-block-definition: P0-PROOF-11 -->
```toml pair-block
id = "P0-PROOF-11"
requirements = ["SIG-04"]
targets = ["tests/test_documentation.py:test_system_graph_contract_compiler_is_total"]
tests = ["tests/test_documentation.py:test_system_graph_contract_compiler_is_total"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k system_graph_contract_compiler_is_total -q"
depends_on = ["P0-SIG-04", "P0-SIG-09"]
```

Require every requirement and verifier rule to reach its owner, tests,
checklist task, PairBlock, targets, gate, and prerequisites. Mutate away each
declaration class and require a specific `SGC` failure.

<!-- pair-block-definition: P0-PROOF-12 -->
```toml pair-block
id = "P0-PROOF-12"
requirements = ["SIG-04"]
targets = ["tests/test_inspection.py:test_blast_coverage_rejects_missing_statement_and_branch"]
tests = ["tests/test_inspection.py:test_blast_coverage_rejects_missing_statement_and_branch"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k blast_coverage_rejects_missing_statement_and_branch -q"
depends_on = ["P0-SIG-10"]
```

Use a fixture with one unexecuted statement and one unexecuted branch. Prove
`SGB002` and `SGB003` independently, then add the missing test cases and require
a complete `BlastCoverageReport`.

## 6. Phase 0 kill gate

Phase 0 closes only when all conditions hold:

- every tracked behavior-bearing file has one matching receipt;
- every registered Python dependency site has one terminal receipt;
- every graph edge uses the canonical dependency direction and carries exact
  evidence;
- the contract compiler resolves contract and rule declarations and generates
  the delta, overlay, impact closure, and rule lowering without reading a
  manually enumerated dependency or PairBlock list;
- strict diagnostics are empty in `B`;
- SCC condensation is canonical and acyclic;
- the propagation plan covers every affected and introduced node exactly once;
- target compilation emits only the three atomic operators over the four Phase
  0 graph facts, rejects contradictions, and produces canonical bytes;
- conformance emits exactly one receipt per target constraint;
- selected tests execute every affected statement and branch arc;
- both committed replay fixtures reproduce every reviewed affected path;
- two compiles produce identical bytes.

The kill-gate report records missed surfaces, false-positive paths, selected
test count, statement and branch obligations, unresolved sites, SCC sizes,
condensation depth, wall time, and peak memory. Phase 1 begins only if the
compiler improves missed-surface detection or review completeness at an
acceptable analysis cost on the replay fixtures.

## 7. Phase 1 high-return PairBlocks

<!-- pair-block-definition: P1-SIG-01 -->
```toml pair-block
id = "P1-SIG-01"
requirements = ["SIG-02"]
targets = ["src/viper/system_graph.py:observe_dynamic_dependencies"]
tests = ["tests/test_validation_architecture.py:test_dynamic_dependency_observation_is_total"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k dynamic_dependency_observation_is_total -q"
depends_on = ["P0-SIG-11"]
```

Observe importlib targets, decorator registrations, literal registries,
reflection targets, and subprocess entrypoints under `SystemContextManifest`.
Require exactly one observation or unresolved outcome per attempt.

<!-- pair-block-definition: P1-SIG-02 -->
```toml pair-block
id = "P1-SIG-02"
requirements = ["SIG-01", "SIG-04"]
targets = ["src/viper/system_graph.py:analyze_structured_documents"]
tests = ["tests/test_documentation.py:test_structured_document_dependencies_are_anchored"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k structured_document_dependencies_are_anchored -q"
depends_on = ["P0-SIG-11"]
```

Add TOML, YAML, JSON, and non-contract Markdown analyzers only for identifiers
already named by active contracts, protocol models, configuration, or tests.
Each analyzer declares its supported site registry and emits receipts.

<!-- pair-block-definition: P1-SIG-03 -->
```toml pair-block
id = "P1-SIG-03"
requirements = ["SIG-02", "SIG-03"]
targets = ["src/viper/inspection.py:system_impact", "src/viper/cli.py:add_system_graph"]
tests = ["tests/test_inspection.py:test_system_impact_artifacts_are_reproducible", "tests/test_cli.py:test_system_impact_command_emits_diagnostics"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py tests/test_cli.py -k system_impact -q"
depends_on = ["P1-SIG-01", "P1-SIG-02"]
```

Publish canonical artifacts and expose one inspection operation plus `viper
system impact`. The CLI renders diagnostics for humans and returns the same
machine JSON as the Python operation.

<!-- pair-block-definition: P1-SIG-04 -->
```toml pair-block
id = "P1-SIG-04"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:partition_condensation_baseline"]
tests = ["tests/test_inspection.py:test_partition_baseline_preserves_scc_atomicity"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k partition_baseline_preserves_scc_atomicity -q"
depends_on = ["P1-SIG-03"]
```

Record SCC size, condensation depth, fan-in, fan-out, cut edges, and affected
statement count. Apply a deterministic greedy grouping over condensation
vertices. Require complete, disjoint ownership of `B`, whole-SCC work units,
and stable output. Preserve the metrics needed to compare this baseline with Co-Coder-style
cohesion-aware partitioning later.

## 8. Commit boundaries

1. `Define canonical SystemGraph vocabulary and diagnostics`
2. `Extract source-evidenced Python dependencies`
3. `Compile contract deltas into conservative impact graphs`
4. `Condense affected cycles and compile target constraints`
5. `Require selected tests to cover the executable blast`
6. `Add observed and persisted SystemGraph tooling`

## 9. Design sources

- Python [`ast`](https://docs.python.org/3/library/ast.html) supplies syntax
  classes and exact source coordinates.
- Python [`symtable`](https://docs.python.org/3/library/symtable.html) supplies
  compiler-derived identifier scopes.
- Tarjan's [depth-first search and SCC
  algorithm](https://doi.org/10.1137/0201010) supplies the linear-time cycle
  decomposition.
- Python [`graphlib`](https://docs.python.org/3/library/graphlib.html) supplies
  an independent DAG/topological-order oracle and documents insertion-sensitive
  ready ordering.
- [Coverage.py branch
  measurement](https://coverage.readthedocs.io/en/latest/branch.html) supplies
  possible and executed line arcs.
- [pytest-cov test
  contexts](https://pytest-cov.readthedocs.io/en/stable/contexts.html) associate
  executed lines and arcs with exact pytest node IDs.
- Horwitz, Reps, and Binkley's [system dependence graph and interprocedural
  slicing](https://doi.org/10.1145/77606.77608) supplies the conservative
  reachability foundation.
- Clarke, Helvensteijn, and Schaefer's [abstract delta
  modeling](https://doi.org/10.1145/1868294.1868298) supplies explicit,
  composable modification semantics.
- Murphy, Notkin, and Sullivan's [software reflexion
  models](https://doi.org/10.1109/32.917525) supplies intended-versus-observed
  structural comparison.
- [Co-Coder](https://arxiv.org/abs/2606.00953) supplies the later
  communication-versus-computation partition objective.
