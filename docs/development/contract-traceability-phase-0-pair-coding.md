# Contract traceability Phase 0 pair-coding guide

This guide divides the contract-requirement traceability compiler into six
pair-coding cycles. The
[contract](contract-requirement-traceability.md) defines the required result.
The [master checklist](master-execution-checklist.md) determines when each
cycle may begin. The exact `pair-edit` code remains in the
[Phase 0 reference](phase-0-pair-coding.md#3-contract-traceability) until the
compiler has executed those edits and the old combined reference can retire.

The repository uses `CRT` as the sole identifier for contract-requirement
traceability. `CST` remains unused.

## 1. Status and boundary

**Guide status:** reviewed against `main` at commit `02273c7`; implementation
pending.

The persisted models already exist in
`src/viper/_contract_traceability.py`. Phase 0 adds the parser, joins,
validation, canonical compiler, and acceptance tests. The broader `SystemGraph`
compiler belongs to its own phase.

The phase starts with these existing records:

```text
ContractRequirement
VerifierRule
RuleEdge
ContractTrace
ContractTraceabilityGraph
```

The phase ends when repository declarations compile into one canonical
`ContractTraceabilityGraph` and every implemented edge resolves to an existing
Python symbol.

## 2. Compiler path

The compiler performs one ordered join:

```text
contract requirement rows
-> verifier-rule rows
-> checklist implementation and verification markers
-> accepted and rejected contract traces
-> ContractTraceabilityGraph
-> canonical JSON bytes
```

Each cycle owns one connector in that path. A cycle closes only after its
focused gate passes and the saved diff matches the named target.

## 3. Pair-coding cycles

### Cycle 1 — requirement and rule declarations

<!-- pair-cycle: P0-CRT-01 -->

**PairBlock:** `P0-CRT-01`  
**Requirements:** `CRT-01`  
**Target:** `_parse_requirement_markers()` and `_parse_verifier_rules()` in
`src/viper/_contract_traceability.py`  
**Depends on:** `P0-PDR-05`

The user adds the regex declarations, `_RequirementMarker`, duplicate-ID
checks, requirement ownership checks, and canonical ordering. Codex inspects
the exact Markdown rows and compares the parser with the current documentation
oracle.

**Focused gate:**

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k contract_rules_map_to_owners_and_tests -q
```

**Stop condition:** one contract produces ordered `ContractRequirement` and
`VerifierRule` tuples; a duplicate requirement, duplicate rule, mismatched
label, unknown requirement, or orphan requirement fails with the exact
identifier.

### Cycle 2 — implementation and verification edges

<!-- pair-cycle: P0-CRT-02 -->

**PairBlock:** `P0-CRT-02`  
**Requirements:** `CRT-02`  
**Target:** `_parse_rule_edges()` and its symbol helpers in
`src/viper/_contract_traceability.py`  
**Depends on:** `P0-CRT-01`

The user parses precise checklist markers, derives their phase and line,
constructs `RuleEdge`, and resolves implemented Python symbols through the AST.
One rule accepts exactly one implementation edge and one or more verification
edges.

**Focused gate:**

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k contract_rules_map_to_owners_and_tests -q
```

**Stop condition:** every parsed rule reaches one source owner and at least one
test function. Unknown rules, phase mismatches, duplicate edges, missing files,
and missing implemented symbols fail at the parser boundary.

### Cycle 3 — traces and worked examples

<!-- pair-cycle: P0-CRT-03 -->

**PairBlock:** `P0-CRT-03`  
**Requirements:** `CRT-03`  
**Targets:** `parse_contract_traces()` and `validate_contract_example()` in
`src/viper/_contract_traceability.py`  
**Depends on:** `P0-CRT-02`

The user parses `toml contract-trace` fences into `ContractTrace`, resolves
their repository symbols, and rejects placeholders. The example validator
requires current, proposed-change, and integrated DAGs plus one marked example
that constructs every Section 4 model.

**Focused gate:**

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k 'contract_traces_are_populated or phase_zero_contracts_show_three_dags' \
  -q
```

**Stop condition:** each selected contract supplies at least one accepted trace
and one rejected trace with concrete values. Missing DAGs, missing model
construction, duplicate trace IDs, placeholders, and unresolved implemented
symbols fail deterministically.

### Cycle 4 — complete contract migration

<!-- pair-cycle: P0-CRT-04 -->

**PairBlock:** `P0-CRT-04`  
**Requirements:** `CRT-03`  
**Target:** `CONTRACTS_WITH_COMPLETE_EXAMPLES` in
`tests/test_documentation.py`  
**Depends on:** `P0-CRT-03`

The user updates each remaining implementation contract to the three-DAG,
complete-example, accepted-trace, and rejected-trace format. Add one contract
at a time to `CONTRACTS_WITH_COMPLETE_EXAMPLES`; run the focused gate after
each addition.

**Focused gate:**

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k phase_zero_contracts_show_three_dags_and_instantiate_models -q
```

**Stop condition:** `CONTRACTS_WITH_COMPLETE_EXAMPLES` equals
`IMPLEMENTATION_CONTRACTS`, and every listed contract passes the same
structural checks.

### Cycle 5 — canonical graph compiler

<!-- pair-cycle: P0-CRT-05 -->

**PairBlock:** `P0-CRT-05`  
**Requirements:** `CRT-04`  
**Targets:** `compile_contract_traceability()` and
`serialize_contract_traceability()` in
`src/viper/_contract_traceability.py`  
**Depends on:** `P0-CRT-03`, `P0-CRT-04`

The user joins every declaration, edge, and trace. The compiler rejects IDs
owned by several contracts, sorts every collection by its declared canonical
key, and serializes compact JSON with sorted object keys.

**Focused gate:**

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k contract_traceability_graph_is_canonical -q
```

**Stop condition:** two compilations from the same repository produce equal
graphs and byte-identical JSON. The graph covers every selected requirement and
rule.

### Cycle 6 — acceptance proof and state promotion

<!-- pair-cycle: P0-PROOF-01 -->
<!-- pair-cycle: P0-PROOF-02 -->
<!-- pair-cycle: P0-PROOF-03 -->
<!-- pair-cycle: P0-PROOF-04 -->

**PairBlocks:** `P0-PROOF-01` through `P0-PROOF-04`  
**Requirements:** `CRT-01` through `CRT-04`  
**Target:** focused traceability tests in `tests/test_documentation.py`  
**Depends on:** `P0-CRT-05`

The user adds one connected temporary-repository builder and varies only the
declaration being rejected. The proof set covers duplicate or orphan
declarations, missing implementation and test symbols, incomplete traces and
examples, and non-canonical graph bytes.

After the rejection tests pass, change each completed CRT implementation and
verification marker from `state="planned"` to `state="implemented"`. Recompile
the graph so symbol resolution checks the compiler and tests themselves.

**Focused gate:**

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k 'contract_rules or contract_trace or phase_zero_contracts' -q
```

**Stop condition:** all four CRT requirements pass their accepted and rejected
cases while every CRT edge uses `state="implemented"`.

## 4. Pairing rule

Each working turn handles one cycle or one contract migration inside Cycle 4:

```text
inspect current file
-> user applies one bounded edit
-> Codex inspects saved code
-> user runs the focused gate
-> pair interprets the exact result
-> commit and push the closed cycle
```

A failed gate keeps the pair in the current cycle. A mechanical propagation
may remain inside one cycle when splitting it would leave the module unable to
import.

## 5. Phase gate

Run the complete documentation boundary after all six cycles:

```bash
conda run -n mantra python -m pytest tests/test_documentation.py -q
```

Then run the SystemGraph contract-compiler tests because that compiler consumes
the completed traceability graph:

```bash
conda run -n mantra python -m pytest \
  tests/test_documentation.py \
  -k 'contract_compiler or system_graph_preserves_contract_traceability' -q
```

Phase 0 contract traceability closes when both commands pass, the graph bytes
remain stable across repeated compilation, the worktree is clean, and the
review-cycle commit is synchronized with its upstream.

## 6. SystemGraph handoff

`compile_contract_traceability()` returns the only traceability input accepted
by `compile_contract_delta()`. The SystemGraph phase consumes:

```text
ContractTraceabilityGraph.requirements
ContractTraceabilityGraph.rules
ContractTraceabilityGraph.edges
ContractTraceabilityGraph.traces
```

The SystemGraph compiler lowers each `RuleEdge` into its canonical dependency
direction. Contract traceability owns parsing and cardinality. SystemGraph owns
dependency lowering, impact traversal, propagation coverage, and target
constraints.
