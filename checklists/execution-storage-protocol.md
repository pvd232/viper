# Execution Storage Protocol

This checklist governs VIPER execution behavior where declared artifact paths, storage destinations, cloud publication, metrics, verification, and retention meet. It is repository-level infrastructure work, not a CleaRx-specific repair.

<!-- contract-protocol:generated:start -->
### Phase 1: Preserve execution paths across storage destinations

| Requirement | Status | Contract | PairBlocks | Dependencies |
|---|---|---|---|---|
| <nobr><code>EPP-REQ-01</code></nobr> | planned | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-01) | <nobr><code>EPP-PB-01</code></nobr> | None |
| <nobr><code>EPP-REQ-02</code></nobr> | planned | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-02) | <nobr><code>EPP-PB-01</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr> |
| <nobr><code>EPP-REQ-03</code></nobr> | planned | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-03) | <nobr><code>EPP-PB-02</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr>, <nobr><code>EPP-REQ-02</code></nobr> |
| <nobr><code>EPP-REQ-04</code></nobr> | planned | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-04) | <nobr><code>EPP-PB-02</code></nobr> | <nobr><code>EPP-REQ-03</code></nobr> |
| <nobr><code>EPP-REQ-05</code></nobr> | planned | [execution-path-parity](../contracts/execution-path-parity.md#epp-req-05) | <nobr><code>EPP-PB-02</code></nobr> | <nobr><code>EPP-REQ-01</code></nobr>, <nobr><code>EPP-REQ-02</code></nobr>, <nobr><code>EPP-REQ-03</code></nobr>, <nobr><code>EPP-REQ-04</code></nobr> |
<!-- contract-protocol:generated:end -->

The execution order restores the public path invariant first, then validates cloud publication, metrics, file-access receipts, retention, and code review evidence against that invariant.
