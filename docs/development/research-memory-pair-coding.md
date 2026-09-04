# Research Memory Pair-Coding Guide

Use this guide to implement Master Phases 18–20 of the
[VIPER Master Execution Checklist](master-execution-checklist.md). The
governing contract is
[Research Memory and Agent Learning](research-memory-roadmap.md). The MCP
boundary also follows [Provenance catalog and MCP](provenance-catalog-mcp.md).

## 1. Status and prerequisite gate

**Guide status:** audited; execution pending contract approval and Master Phase 17.

Tomorrow's first repository action remains the first open block in the master
checklist. Do not start `P18-RML-01` until these facts are true:

```text
Master Phase 0 System Impact Check passes
Master Phase 12 experiment expansion and bounded execution pass
Master Phase 15 MCP server passes
Master Phase 16 scientific evidence records pass
Master Phase 17 knowledge graph and agent search pass
```

This ordering is functional, not administrative. `ResearchEpisode` cites the
verified runs, knowledge records, catalog snapshots, MCP receipts, System
Impact Check records, and PairBlocks produced by those phases.

Run repository-owned Python commands through:

```bash
python ...
```

Before each PairBlock, confirm the interpreter is:

```text
<repository>/.venv/bin/python
```

## 2. Pair cycle

For each PairBlock:

1. Read the named contract section and current target files.
2. Apply only the bounded edit in that block.
3. Run the focused check.
4. Inspect the actual result together.
5. Update the master-checklist box only after the check passes.
6. Commit at the stated boundary after every block in that boundary passes.

Do not combine a failing block with the next block. Record a contract gap when
the implementation cannot represent or verify a required value.

`depends_on` contains PairBlock IDs only. The master checklist owns
cross-phase entry gates; the first Master Phase 18 block therefore has no
PairBlock predecessor even though Master Phase 18 cannot start until its
listed Master Phase prerequisites pass.

Every block uses the shared six-field PairBlock manifest: `id`,
`requirements`, `targets`, `tests`, `gate`, and `depends_on`. A target names an
exact implementation symbol as `path:symbol`; a test names an exact observing
test the same way. The block ID and its checklist marker identify the owning
Master Phase, so the manifest does not repeat that phase number. Output types
and functions are targets, not a separate `produces` vocabulary.
Symbols in files that do not exist yet are planned implementation names fixed
by this guide. If an earlier block creates a conflicting symbol, stop and amend
the governing contract and this guide before continuing.

## 3. Dependency graph

```mermaid
flowchart TB
    A["P18-RML-01 Core records"] --> B["P18-RML-02 Selection"]
    B --> C["P18-RML-03 Episode"]
    C --> D["P18-RML-04 Publication"]
    D --> E["P18-RML-05 Verification"]
    E --> F["P18-RML-06 Episode acceptance"]
    F --> G["P19-RML-01 Learning dataset"]
    G --> H["P19-RML-02 Evaluation"]
    H --> I["P19-RML-03 Promotion gate"]
    I --> J["P20-RML-01 Research MCP"]
    J --> K["P20-RML-02 MCP tasks"]
    K --> L["P20-RML-03 Literature"]
    L --> M["P20-RML-04 Integrated gate"]

    class A,B,C,D,E,F contract
    class G,H,I evidence
    class J,K implementation
    class L,M output
    classDef contract fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef evidence fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef implementation fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px
    classDef output fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

## 4. Research episodes (Master Phase 18)

### P18-RML-01 — core research records

```toml pair-block
id = "P18-RML-01"
requirements = ["RML-01"]
depends_on = []
targets = ["src/viper/research.py:ResearchObjectiveId", "src/viper/research.py:HypothesisId", "src/viper/research.py:CandidateId", "src/viper/research.py:EpisodeId", "src/viper/research.py:PolicyId", "src/viper/research.py:DatasetId", "src/viper/research.py:ResearchConstraintId", "src/viper/research.py:ResearchConstraint", "src/viper/research.py:ResearchObjective", "src/viper/research.py:AnalysisPlan", "src/viper/research.py:HypothesisSpec", "src/viper/research.py:ResourceLimit", "src/viper/research.py:ResourceBudget"]
tests = ["tests/test_protocol.py:test_research_core_records_are_frozen_and_canonical"]
gate = "python -m pytest tests/test_protocol.py -k research_core_records_are_frozen_and_canonical -q"
```

Add the exact identifier aliases and six models from Sections 6 and 7 of the
contract. Keep them in `viper.research`; do not re-export them from
`viper.__init__`. Add field, frozen-model, invalid-enum, finite-number, and JSON
round-trip tests.

Focused check:

```bash
python -m pytest tests/test_protocol.py -q
```

Stop if the existing schema owners require a different exact reference type.
Record that mismatch in the contract before changing the public name.

### P18-RML-02 — candidates and selection

```toml pair-block
id = "P18-RML-02"
requirements = ["RML-01", "RML-02"]
depends_on = ["P18-RML-01"]
targets = ["src/viper/research.py:ExperimentCandidate", "src/viper/research.py:SelectionPolicyIdentity", "src/viper/research.py:CandidateScore", "src/viper/research.py:ExperimentSelection"]
tests = ["tests/test_protocol.py:test_experiment_selection_is_total_and_budgeted"]
gate = "python -m pytest tests/test_protocol.py -k experiment_selection_is_total_and_budgeted -q"
```

Implement the candidate and selection models. Add validators for unique
candidate IDs, one score per candidate, selected-candidate membership,
eligibility, selection probability for randomized or learned policies, and the
declared `ResourceBudget`. Resolve every candidate constraint to its objective
and record the seed for each stochastic selector.

The fixture contains three candidates: one selected, one eligible and
unselected, and one ineligible with a rejection reason. Preserve all three.

Focused check:

```bash
python -m pytest tests/test_protocol.py -q
```

### P18-RML-03 — invocation receipts and complete episode

```toml pair-block
id = "P18-RML-03"
requirements = ["RML-01"]
depends_on = ["P18-RML-02"]
targets = ["src/viper/research.py:AgentModelIdentity", "src/viper/research.py:AgentPolicyIdentity", "src/viper/research.py:AgentModelInvocationReceipt", "src/viper/research.py:AgentToolInvocationReceipt", "src/viper/research.py:ResearchObservation", "src/viper/research.py:ResearchReview", "src/viper/research.py:ResearchEpisode"]
tests = ["tests/test_protocol.py:test_research_episode_preserves_decision_and_execution_provenance"]
gate = "python -m pytest tests/test_protocol.py -k research_episode_preserves_decision_and_execution_provenance -q"
```

Implement the exact model identity, policy, invocation, observation, review,
and episode models. The complete fixture must reference:

```text
one ResearchObjective
one preregistered HypothesisSpec
one ExperimentSelection
one AgentPolicyIdentity, policy bundle, and memory manifest
one model receipt
at least one tool receipt with server version and tool-schema digest
one generated PairBlock reference
at least one verified ResolvedRunRef
all measurement, effect, diagnostic, and failure references
one terminal ResearchReview
recomputed cost and wall time
```

Focused check:

```bash
python -m pytest tests/test_protocol.py -q
```

### P18-RML-04 — immutable publication

```toml pair-block
id = "P18-RML-04"
requirements = ["RML-01"]
depends_on = ["P18-RML-03"]
targets = ["src/viper/research.py:ResearchRecordKind", "src/viper/research.py:ResearchRecord", "src/viper/research.py:ResearchRecordEnvelope", "src/viper/research.py:ResearchManifest", "src/viper/research.py:publish_research_record", "src/viper/catalog.py:Catalog.refresh"]
tests = ["tests/test_inspection.py:test_research_manifest_rebuild_is_canonical"]
gate = "python -m pytest tests/test_inspection.py -k research_manifest_rebuild_is_canonical -q"
```

Implement the closed `ResearchRecordKind` and `ResearchRecord` unions.
Canonicalize and publish each envelope through the existing immutable-file
publisher. Write one `ResearchManifest`, then replace
`.viper/research/head.json` atomically under the repository lock.

Extend `Catalog.refresh()` to walk local and supplied research heads, reject
cycles and wrong record kinds, keep every source `ResolvedFileRef`, and rebuild
equal rows after deletion.

Focused check:

```bash
python -m pytest tests/test_inspection.py -q
```

### P18-RML-05 — research verification

```toml pair-block
id = "P18-RML-05"
requirements = ["RML-01", "RML-02"]
depends_on = ["P18-RML-04"]
targets = ["src/viper/verification/__init__.py:verify_research_record", "src/viper/_verification/research.py:verify_research_record"]
tests = ["tests/test_verification_acceptance.py:test_research_verifier_rejects_invalid_episode"]
gate = "python -m pytest tests/test_verification_acceptance.py -k research_verifier_rejects_invalid_episode -q"
```

Verify every nested reference and every recomputable value. Add the exact
rejection cases from Section 15 of the contract through `ResearchEpisode`.
Particularly test:

```text
registered_at after a result
candidate or score set mismatch
ineligible selection
budget mismatch
missing selection probability
receipt digest mismatch
unresolved PairBlock or run
fixed interval with anytime stopping
unrecomputed multiplicity claim
```

Focused check:

```bash
python -m pytest tests/test_verification_acceptance.py -q
```

### P18-RML-06 — complete episode acceptance

```toml pair-block
id = "P18-RML-06"
requirements = ["RML-01", "RML-02"]
depends_on = ["P18-RML-05"]
targets = ["tests/test_protocol.py:test_research_episode_round_trip", "tests/test_inspection.py:test_research_episode_is_queryable_from_every_identity", "tests/test_verification_acceptance.py:test_research_episode_acceptance_covers_validity_failures"]
tests = ["tests/test_protocol.py:test_research_episode_round_trip", "tests/test_inspection.py:test_research_episode_is_queryable_from_every_identity", "tests/test_verification_acceptance.py:test_research_episode_acceptance_covers_validity_failures"]
gate = "python -m pytest tests/test_protocol.py tests/test_inspection.py tests/test_verification_acceptance.py -q"
```

Publish and verify the complete fixed-budget fixture. Delete and rebuild the
catalog. Query the episode from the question, selected candidate, run,
diagnostic, and policy directions. Then run:

```bash
python -m pytest \
  tests/test_protocol.py \
  tests/test_inspection.py \
  tests/test_verification_acceptance.py -q
```

**Commit boundary:** `Record auditable research episodes`

## 5. Learning and promotion (Master Phase 19)

### P19-RML-01 — group-safe learning dataset

```toml pair-block
id = "P19-RML-01"
requirements = ["RML-03"]
depends_on = ["P18-RML-06"]
targets = ["src/viper/research.py:LearningOrigin", "src/viper/research.py:LearningTarget", "src/viper/research.py:LearningExample", "src/viper/research.py:DatasetMember", "src/viper/research.py:DatasetSplit", "src/viper/research.py:LeakageCheck", "src/viper/research.py:LearningDatasetManifest", "src/viper/catalog.py:Catalog.refresh"]
tests = ["tests/test_protocol.py:test_learning_dataset_manifest_preserves_origin_and_splits", "tests/test_verification_acceptance.py:test_learning_dataset_rejects_group_and_time_leakage"]
gate = "python -m pytest tests/test_protocol.py tests/test_verification_acceptance.py -q"
```

Implement curation and manifest records. Group by research question, source
dataset, benchmark family, and paper-replication task before assigning splits.
Reject any group crossing a split, any post-cutoff record, any unreviewed
label, and any synthetic example without complete ancestors and origin counts.

Focused check:

```bash
python -m pytest tests/test_protocol.py tests/test_verification_acceptance.py -q
```

### P19-RML-02 — baseline and challenger evaluation

```toml pair-block
id = "P19-RML-02"
requirements = ["RML-04"]
depends_on = ["P19-RML-01"]
targets = ["src/viper/research.py:LearningUpdateSpec", "src/viper/research.py:LearningUpdateReceipt", "src/viper/research.py:EvaluationMetric", "src/viper/research.py:AgentEvaluationPlan", "src/viper/research.py:AgentEvaluationResult"]
tests = ["tests/test_protocol.py:test_agent_evaluation_records_baseline_challenger_and_gates", "tests/test_verification_acceptance.py:test_agent_evaluation_recomputes_slice_gates"]
gate = "python -m pytest tests/test_protocol.py tests/test_verification_acceptance.py -q"
```

Implement `memory_publish` first. Freeze the baseline and challenger policy,
task set, tool schemas, budgets, seeds, primary metrics, retention metrics, and
context slices. Run both policies on the same fixtures. Store task-level
results and recompute every gate.

Focused check:

```bash
python -m pytest tests/test_protocol.py tests/test_verification_acceptance.py -q
```

### P19-RML-03 — promotion and rollback

```toml pair-block
id = "P19-RML-03"
requirements = ["RML-04"]
depends_on = ["P19-RML-02"]
targets = ["src/viper/research.py:PolicyPromotionDecision"]
tests = ["tests/test_verification_acceptance.py:test_policy_promotion_requires_passing_gates_and_rollback"]
gate = "python -m pytest tests/test_verification_acceptance.py -k policy_promotion_requires_passing_gates_and_rollback -q"
```

Require a passing evaluation, explicit promotion reviewer, and loadable rollback policy.
Reject a challenger that improves the aggregate while one retention slice
fails. Promote the passing retrieval-memory challenger, load it, then load and
smoke-test the recorded rollback policy.

Focused check:

```bash
python -m pytest tests/test_verification_acceptance.py -q
```

**Commit boundary:** `Evaluate and promote reviewed research memory`

## 6. Research MCP and literature (Master Phase 20)

### P20-RML-01 — research resources, prompts, model invocation, and elicitation

```toml pair-block
id = "P20-RML-01"
requirements = ["RML-05", "PCM-06"]
depends_on = ["P19-RML-03"]
targets = ["src/viper/api.py:OperationName", "src/viper/api.py:OPERATIONS", "src/viper/api.py:REQUEST_REGISTRY", "src/viper/api.py:HANDLER_REGISTRY", "src/viper/mcp.py:create_server", "src/viper/cli.py:main"]
tests = ["tests/test_api.py:test_research_mcp_schemas_resources_prompts_and_review_custody", "tests/test_cli.py:test_mcp_learn_access_isolated"]
gate = "python -m pytest tests/test_api.py tests/test_cli.py -q"
```

Add the exact research operations to the typed API registry. Add `learn`
access, research `viper://` resources and templates, research prompts,
provider-backed model invocation with `AgentModelInvocationReceipt`, and MRTR
form-mode review elicitation. Add stateless request metadata and
`server/discover`; prove omission when capabilities or access are absent.
Decline authorizes nothing.
The CLI boundary is `viper mcp --root <path> --access learn`.

Focused check:

```bash
python -m pytest tests/test_api.py tests/test_cli.py -q
```

### P20-RML-02 — task parity

```toml pair-block
id = "P20-RML-02"
requirements = ["PCM-07"]
depends_on = ["P20-RML-01"]
targets = ["src/viper/mcp.py:create_server"]
tests = ["tests/test_api.py:test_research_tasks_preserve_operation_identity", "tests/test_cli.py:test_research_tasks_match_ordinary_status_and_cancellation"]
gate = "python -m pytest tests/test_api.py tests/test_cli.py -q"
```

Advertise `io.modelcontextprotocol/tasks` only for the four operations named by
the MCP contract. Map each MCP task to the existing durable VIPER operation ID.
Route `tasks/get`, `tasks/update`, and `tasks/cancel` through the same operation
state. Execute each fixture with and without the extension and compare status,
cancellation, result, and side effects.

Focused check:

```bash
python -m pytest tests/test_api.py tests/test_cli.py -q
```

### P20-RML-03 — anchored literature

```toml pair-block
id = "P20-RML-03"
requirements = ["RML-06"]
depends_on = ["P20-RML-02"]
targets = ["src/viper/research.py:LiteratureWork", "src/viper/research.py:LiteratureVersion", "src/viper/research.py:EvidenceAnchor", "src/viper/research.py:LiteratureClaim", "src/viper/catalog.py:Catalog.refresh"]
tests = ["tests/test_inspection.py:test_literature_records_rebuild_and_link_to_research", "tests/test_verification_acceptance.py:test_literature_verifier_rejects_invalid_versions_and_anchors"]
gate = "python -m pytest tests/test_inspection.py tests/test_verification_acceptance.py -q"
```

Implement literature records, version chains, exact source anchors, extraction
origin, review state, correction and retraction state, catalog queries, and the
four literature-to-research edges. Export one verified bundle as a derived
RO-Crate and verify that deleting the export changes no VIPER evidence.

Focused check:

```bash
python -m pytest tests/test_inspection.py tests/test_verification_acceptance.py -q
```

### P20-RML-04 — integrated gate

```toml pair-block
id = "P20-RML-04"
requirements = ["RML-05", "RML-06", "PCM-06", "PCM-07"]
depends_on = ["P20-RML-03"]
targets = ["tests/test_api.py:test_research_mcp_end_to_end", "tests/test_cli.py:test_research_mcp_end_to_end", "tests/test_inspection.py:test_research_catalog_rebuild_end_to_end", "tests/test_verification_acceptance.py:test_research_learning_and_literature_acceptance", "tests/test_contract_documentation.py:test_research_pair_guide_has_executable_ordered_blocks"]
tests = ["tests/test_api.py:test_research_mcp_end_to_end", "tests/test_cli.py:test_research_mcp_end_to_end", "tests/test_inspection.py:test_research_catalog_rebuild_end_to_end", "tests/test_verification_acceptance.py:test_research_learning_and_literature_acceptance", "tests/test_contract_documentation.py:test_research_pair_guide_has_executable_ordered_blocks"]
gate = "python -m pytest tests/test_api.py tests/test_cli.py tests/test_inspection.py tests/test_verification_acceptance.py tests/test_contract_documentation.py -q"
```

Run the complete research/MCP boundary:

```bash
python -m pytest \
  tests/test_api.py \
  tests/test_cli.py \
  tests/test_inspection.py \
  tests/test_verification_acceptance.py \
  tests/test_contract_documentation.py -q
```

Then run the change-aware test boundary reported for the final diff. Fix every
in-scope failure before closing Master Phase 20.

**Commit boundary:** `Expose verified research learning through MCP`

## 7. Tomorrow's shutdown handoff

Record:

```text
last completed PairBlock
focused command and exact result
changed files
first failing assertion, if any
next PairBlock
uncommitted paths
current commit and upstream status
```

The next session starts from that exact PairBlock boundary, not from a prose
summary of the intended system.
