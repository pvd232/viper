# CFO-PB-06

**Requirements:** CFO-REQ-03, CFO-REQ-06, CFO-REQ-07, CFO-REQ-09

**Depends on:** PB04 and PB05

**Status:** Native workflow and durable publication are committed and pass the final fast gate; all 227 selected integration cases pass across retained bounded runs.

The defining owners are [PublicationSession and its records](../../../src/viper/_offload.py), [the detached worker](../../../src/viper/execution/_offload_worker.py), [the shared resolver and public status interface](../../../src/viper/storage.py), and the native authoring/execution entry points. Thread tasks borrow the outer owner explicitly. Stage and metric children acquire their own reader locks. Physical output files belong to individual attempts, while references and checked access receipts keep logical addresses.

Original output paths are registered and durably admitted before acceptance. The worker transfers and verifies them independently. Pending source obligations remain after runner exit and between retries. Existing synchronous cloud-returning calls retain their completion promises. Public workflow/status/copy/receipt/retry interfaces are defined in storage.py.

The final source-membership repair at `df10a3e` captures the original Git commit and directory objects in private `GitFileProof` metadata. Native closure and explicit enrollment carry source bytes and those proofs through existing auxiliary local snapshots. Receipt import restores the checked Git-address index; it does not invent a Git snapshot or change references or receipt fields. A matching payload SHA alone is insufficient to authorize a pinned Git path.

Observing definitions are in tests/test_background_publication.py, tests/test_offload_workflow.py, tests/test_offload_recovery.py, tests/test_git_proof.py and tests/test_managed_file_access.py. The canonical contract identifies the required cases. The retained [final fast gate](../../../evidence/cloud-offload-implementation-20261125/validation/make-check.log) passes at `df10a3e`; [the repaired fresh-workspace observer](../../../evidence/cloud-offload-integration-20261125/git-fresh-producer.log) passes in 125.68 seconds. The retained [integration coverage record](../../../evidence/cloud-offload-integration-20261125/coverage.json) accounts for all 227 selected cases passed across bounded runs.

Source changes and ordinary test logs are distinct from formal acceptance. No lifecycle receipt is created by this document.

Native integration and recovery checkpoints are `1b8ed60` and `c869ea6`; the source verification repair is `c83af457`, followed by the final inventory repair `df10a3e`. The changes are in [draft Viper PR 24](https://github.com/pvd232/viper/pull/24).
