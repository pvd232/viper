# Execution Storage Protocol

This checklist governs VIPER execution behavior where declared artifact paths, storage destinations, cloud publication, metrics, verification, and retention meet. It is repository-level infrastructure work, not a CleaRx-specific repair.

<!-- contract-protocol:generated:start -->
### Phase 1: Preserve execution paths across storage destinations

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>EPP-REQ-01</code></nobr> | complete | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-01) | <nobr><code>EPP-PB-01</code></nobr> | None |
| <nobr><code>EPP-REQ-02</code></nobr> | complete | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-02) | <nobr><code>EPP-PB-01</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr> |
| <nobr><code>EPP-REQ-03</code></nobr> | complete | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-03) | <nobr><code>EPP-PB-02</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr>, <nobr><code>EPP-REQ-02</code></nobr> |
| <nobr><code>EPP-REQ-04</code></nobr> | complete | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-04) | <nobr><code>EPP-PB-02</code></nobr> | <nobr><code>EPP-REQ-03</code></nobr> |
| <nobr><code>EPP-REQ-05</code></nobr> | complete | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-05) | <nobr><code>EPP-PB-02</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr>, <nobr><code>EPP-REQ-02</code></nobr>, <nobr><code>EPP-REQ-03</code></nobr>, <nobr><code>EPP-REQ-04</code></nobr> |

### Phase 2: Reuse pointer-backed stored inputs without manual catalog refresh

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>SRPF-REQ-01</code></nobr> | planned | [stage-reuse-pointer-first](../contracts/stage-reuse-pointer-first.md#srpf-req-01) | <nobr><code>SRPF-PB-01</code></nobr> | None |
| <nobr><code>SRPF-REQ-02</code></nobr> | planned | [stage-reuse-pointer-first](../contracts/stage-reuse-pointer-first.md#srpf-req-02) | <nobr><code>SRPF-PB-01</code></nobr> | <nobr><code>SRPF-REQ-01</code></nobr> |
| <nobr><code>SRPF-REQ-03</code></nobr> | planned | [stage-reuse-pointer-first](../contracts/stage-reuse-pointer-first.md#srpf-req-03) | <nobr><code>SRPF-PB-01</code></nobr> | <nobr><code>SRPF-REQ-01</code></nobr>, <nobr><code>SRPF-REQ-02</code></nobr> |
| <nobr><code>SRPF-REQ-04</code></nobr> | planned | [stage-reuse-pointer-first](../contracts/stage-reuse-pointer-first.md#srpf-req-04) | <nobr><code>SRPF-PB-02</code></nobr> | <nobr><code>SRPF-REQ-03</code></nobr> |
| <nobr><code>SRPF-REQ-05</code></nobr> | planned | [stage-reuse-pointer-first](../contracts/stage-reuse-pointer-first.md#srpf-req-05) | <nobr><code>SRPF-PB-03</code></nobr> | <nobr><code>SRPF-REQ-01</code></nobr>, <nobr><code>SRPF-REQ-04</code></nobr> |
<!-- contract-protocol:generated:end -->

The execution order restores the public path invariant first, validates cloud publication and verification against that invariant, then connects stored-input pointers to verified stage reuse before adding pointer-first stored-input execution.
