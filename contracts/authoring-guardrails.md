# Authoring Guardrails

## 1. Status

**Contract status:** Planned in the [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md) checklist.

<!-- contract-protocol:generated:start -->
**In progress.** [Jump to current PairBlock](#aug-pb-01)

**Checklist:** [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md)

### PairBlocks

<a id="aug-pb-01"></a>

#### <nobr><code>AUG-PB-01</code></nobr>

**Status:** approved

**Requirement contribution:** Enforce the existing terminal-diagnostic rule at authoring and frozen-plan verification boundaries.

**Review handoff**

**What changed**

- Variant authoring rejects an estimator produced by a terminal diagnostic stage.
- Frozen-plan verification independently rejects a hand-edited diagnostic estimator.
- Executable tests replace the previous source-inspection assertion at the authoring boundary and add the persisted-plan counterexample.

**Plan deviations:** No deviations from AUG-REQ-01. The candidate preserves exception-based validation and adds no execution behavior.

**Start review:** [Open tested GitHub comparison](https://github.com/pvd232/viper/compare/70b025c33b57e987a3ec3815389b60415ceb42c6...393bd35c579a5f6902eee20a69c0c46b6e5280c9)

**Review these files**

- [Complete diagnostic-estimator candidate](../plans/authoring-guardrails/AUG-PB-01/patches/diagnostic-estimator.patch#L1)
- [Authoring validation owner](../src/viper/authoring.py#L400)
- [Frozen-plan verification owner](../src/viper/_verification/plan.py#L401)

**Evidence:** [Passing gate receipt](../evidence/gates/aug-pb-01.json)

**Decision:** Approval is recorded for <nobr><code>AUG-PB-01</code></nobr>; review the installed commit.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/authoring-guardrails/AUG-PB-01/plan.toml)

**Retained patch:** [patches/diagnostic-estimator.patch](../plans/authoring-guardrails/AUG-PB-01/patches/diagnostic-estimator.patch)

**Implementation roots:** [pyproject.toml](../pyproject.toml) · [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** None

**Gate steps:**

```bash
# typecheck
(cd . && pyright src/viper/authoring.py src/viper/_verification/plan.py tests/test_diagnostic_stage.py tests/test_verification.py)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_diagnostic_stage.py::test_diagnostic_output_cannot_be_an_estimator tests/test_verification.py::RunPlanRelationshipTests::test_plan_rejects_diagnostic_estimator)
# documentation
(cd . && ruff check --select D src/viper/authoring.py src/viper/_verification/plan.py tests/test_diagnostic_stage.py tests/test_verification.py)
# lint
(cd . && ruff format --check src/viper/authoring.py src/viper/_verification/plan.py tests/test_diagnostic_stage.py tests/test_verification.py)
# lint
(cd . && ruff check src/viper/authoring.py src/viper/_verification/plan.py tests/test_diagnostic_stage.py tests/test_verification.py)
```

</details>

<a id="aug-pb-02"></a>

#### <nobr><code>AUG-PB-02</code></nobr>

**Status:** waiting

**Requirement contribution:** Add deterministic, complete factor-matrix construction without changing variant or expansion semantics.

**Plan:** None

**Current receipt:** None

**Dependencies:** <nobr><code>PED-PB-01</code></nobr>

**Next action:** Wait for the declared dependencies.


### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>AUG-REQ-01</code></nobr> | variant() must reject an estimator produced by a terminal diagnostic stage, and verify_plan() must reject the same invalid selection in a hand-edited frozen plan. | in_progress | <nobr><code>AUG-VR-01</code></nobr> | <nobr><code>AUG-PB-01</code></nobr> |
| <nobr><code>AUG-REQ-02</code></nobr> | matrix() must enumerate the deterministic Cartesian product of named factor levels, invoke one variant factory for each cell in factor declaration order, and reject a missing cell, a returned variant whose levels differ from that cell, or a duplicate variant ID. | planned | <nobr><code>AUG-VR-02</code></nobr> | <nobr><code>AUG-PB-02</code></nobr> |

### Verification rules

| Rule | Requirements | Acceptance conditions | Success case | Rejection cases |
|---|---|---|---|---|
| <nobr><code>AUG-VR-01</code></nobr> | <nobr><code>AUG-REQ-01</code></nobr> | A diagnostic output fails estimator selection through the Python authoring API and through verification of a frozen plan whose estimator was edited to name that output. | [test_diagnostic_output_cannot_be_an_estimator](../tests/test_diagnostic_stage.py) | [test_plan_rejects_diagnostic_estimator](../tests/test_verification.py) |
| <nobr><code>AUG-VR-02</code></nobr> | <nobr><code>AUG-REQ-02</code></nobr> | Two factors with two and three levels produce six variants in stable factor and level order; omitted, mismatched, and duplicate cells fail before experiment construction. | [test_matrix_builds_complete_cartesian_variants_in_order](../tests/test_authoring.py) | [test_matrix_rejects_incomplete_mismatched_or_duplicate_cells](../tests/test_authoring.py) |
<!-- contract-protocol:generated:end -->

## 2. Claim

VIPER rejects terminal diagnostic estimators before execution and constructs complete factor matrices deterministically.

## 3. Models

| Model | Role |
|---|---|
| `VariantDraft.estimator` | Selects the stage output treated as the run's estimator. |
| `DiagnosticSpecDraft` and `DiagnosticSpec` | Mark outputs that may be reported but may not become estimators or downstream inputs. |
| Proposed `matrix()` | Enumerates factor-level cells and obtains one validated `VariantDraft` per cell. |

## 4. Execution

1. `variant()` rejects a diagnostic producer when the author selects the estimator.
2. `verify_plan()` independently rejects the same selection in persisted plan bytes.
3. `matrix()` enumerates named factor levels in declaration order, invokes the factory once per cell, and validates the returned levels and unique variant identity.
4. Existing `experiment()` and `expand()` consume the resulting variants without new execution semantics.

## 5. Persisted evidence

| Record | Evidence |
|---|---|
| Frozen `VariantSpec` and `RunSpec` | The validated factor cell and non-diagnostic estimator selection. |
| PairBlock gate receipt | Authoring, persisted-plan rejection, type, documentation, and Ruff results. |

## 6. Verification

The authoring tests exercise the public constructors; verification tests hand-edit frozen values so the persisted boundary cannot rely on the Python authoring guard.

## 7. Propagation

| Surface | Required change |
|---|---|
| `viper.authoring` | Reject diagnostic estimators and export `matrix()`. |
| Plan verification | Reject a diagnostic stage selected by a frozen `RunSpec`. |
| Public API and docs | Document matrix construction and terminal diagnostic selection. |

## 8. Acceptance case

### Success

Two factors with two and three levels create six variants in stable order, each with a non-diagnostic estimator.

### Rejection

Authoring or verification rejects a diagnostic estimator; matrix construction rejects a missing, mismatched, or duplicate cell.

## 9. Implementation order

1. Enforce terminal diagnostic selection at both validation boundaries.
2. Add the matrix helper and its complete-cell tests.

## 10. Contract-owned PairBlocks

The generated section identifies the independent diagnostic and matrix blocks. Checklist phase order selects the diagnostic guard first without inventing a code dependency between them.

## 11. ContractTarget

Each source-backed plan names its public declarations, protocol checks, tests, and documentation. No PairBlock changes run execution semantics.
