# Final Git source verification amendment

The source candidate is `df10a3e2258a28d7eb276d5a35a5621c0384a694`. [The before-image](before-image.json) preserves the exact immediately preceding documents and raw hashes. This is engineering amendment evidence, not a protocol receipt.

A matching file SHA and size cannot establish membership in a pinned Git commit and path. The private `GitFileProof` checks the Git commit and directory object chain, then checks the payload's Git blob ID, size and SHA-256. Proof metadata travels beside source files through existing auxiliary LOCAL snapshots and completed copy receipts. Import registers the checked Git address without changing original references or adding a public receipt field.

The canonical package keeps all requirements, acceptance conditions and PairBlock dependencies unchanged. Existing identity/recovery verifier bindings now observe changed source bytes, changed commit/directory metadata, another path, stale compiled code, missing membership proof, and ordinary queue/evict/import recovery without Git access. The previous ordinary artifact-import observer and the offline proof success case remain supplemental evidence in the static audit.

The production protocol parser remains unavailable; no installation, canonical package digest or formal acceptance is fabricated. AST/TOML audits establish declaration consistency and actual definitions, not executed test outcomes. The final fast gate passes at `df10a3e`; all 227 selected integration cases pass across retained bounded runs. Executed logs and formal acceptance remain separate. CFO-REQ-10 remains OPEN and unmet.
