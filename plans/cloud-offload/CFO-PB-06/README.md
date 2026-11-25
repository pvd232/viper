# CFO-PB-06

**Requirements:** CFO-REQ-03, CFO-REQ-06, CFO-REQ-07, CFO-REQ-09

**Depends on:** PB04 and PB05

**Status:** Native workflow and durable publication are implemented in the current candidate; review repairs and final broad validation remain in progress.

The defining owners are [PublicationSession and its records](../../../src/viper/_offload.py), [the detached worker](../../../src/viper/execution/_offload_worker.py), [the shared resolver and public status interface](../../../src/viper/storage.py), and the native authoring/execution entry points. Thread tasks borrow the outer owner explicitly. Stage and metric children acquire their own reader locks. Physical output files belong to individual attempts, while references and checked access receipts keep logical addresses.

Original output paths are registered and durably admitted before acceptance. The worker transfers and verifies them independently. Pending source obligations remain after runner exit and between retries. Existing synchronous cloud-returning calls retain their completion promises. Public workflow/status/copy/receipt/retry interfaces are defined in storage.py.

Observing definitions are in tests/test_background_publication.py, tests/test_offload_workflow.py, tests/test_offload_recovery.py and tests/test_managed_file_access.py. The canonical contract identifies the required cases. Broad check and repair recheck results are not yet final.

Source changes and ordinary test logs are distinct from formal acceptance. No lifecycle receipt is created by this document.
