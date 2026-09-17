# CleaRx-Driven VIPER Friction Repairs

This checklist converts the concrete friction observed in the CleaRx audio-retention runs into independently verifiable VIPER changes. It keeps GPU/CPU stage separation and stateless build or metric functions in the existing stage model; those paths did not require a new abstraction.

<!-- contract-protocol:generated:start -->
**Resume here:** [Resume at ARE-PB-02](../contracts/attempt-recovery-and-export.md#are-pb-02)


### Phase 1: Fail invalid plans before execution

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>AUG-REQ-01</code></nobr> | complete | [authoring-guardrails](../contracts/authoring-guardrails.md#aug-req-01) | <nobr><code>AUG-PB-01</code></nobr> | None |

### Phase 2: Retain and resume partial execution

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>ARE-REQ-01</code></nobr> | complete | [attempt-recovery-and-export](../contracts/attempt-recovery-and-export.md#are-req-01) | <nobr><code>ARE-PB-01</code></nobr> | None |
| <nobr><code>ARE-REQ-02</code></nobr> | complete | [attempt-recovery-and-export](../contracts/attempt-recovery-and-export.md#are-req-02) | <nobr><code>ARE-PB-01</code></nobr> | <nobr><code>ARE-REQ-01</code></nobr> |

### Phase 3: Export complete run evidence

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>ARE-REQ-03</code></nobr> | in_progress | [attempt-recovery-and-export](../contracts/attempt-recovery-and-export.md#are-req-03) | <nobr><code>ARE-PB-02</code></nobr> | <nobr><code>ARE-REQ-02</code></nobr> |

### Phase 4: Diagnose Python environments before execution

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>PED-REQ-01</code></nobr> | planned | [python-environment-diagnostics](../contracts/python-environment-diagnostics.md#ped-req-01) | <nobr><code>PED-PB-01</code></nobr> | None |
| <nobr><code>PED-REQ-02</code></nobr> | planned | [python-environment-diagnostics](../contracts/python-environment-diagnostics.md#ped-req-02) | <nobr><code>PED-PB-01</code></nobr> | <nobr><code>PED-REQ-01</code></nobr> |

### Phase 5: Generate complete experiment matrices

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>AUG-REQ-02</code></nobr> | planned | [authoring-guardrails](../contracts/authoring-guardrails.md#aug-req-02) | <nobr><code>AUG-PB-02</code></nobr> | None |
<!-- contract-protocol:generated:end -->

The execution order front-loads invalid-plan rejection, then protects completed computation, packages provenance, improves environment diagnosis, and finishes with authoring ergonomics. Each PairBlock is independently reviewable and may stop without weakening later acceptance criteria.
