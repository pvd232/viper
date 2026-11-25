# CFO-PB-07

**Requirements:** CFO-REQ-05, CFO-REQ-08, CFO-REQ-09

**Depends on:** PB06

**Status:** Cleanup and its worker integration are committed at `95a2420` and pass the final fast gate at `df10a3e`. All selected integration cases pass; hosted PR checks are still running and no formal acceptance is recorded.

[retention.cleanup_operation](../../../src/viper/retention.py) runs from the same detached publication worker. Successful whole-workflow closure requests reconsideration of exact observed copies. Removal rechecks all-target data/final proof, current subscribers, pending sources, readers, ownership and physical identity. Hashing and remote work stay outside the short final registry transaction.

The legacy eviction entry point uses that decision. Managed originals and caches share it; external files and unrelated names remain protected. Complete inventory and references survive eviction. Later cleanup reuses verified proof without reopening uploads.

The active [cleanup suite](../../../tests/test_offload_cleanup.py) observes worker dispatch after publication, ready-upload priority, release after the last reader, current keep policy, stale replacements, hardlinks and external-copy protection. Canonical verifier bindings identify those exact functions. These source bindings are not substituted for executed gate evidence.

Obsolete source/test mirrors for this block were retired after activation. [The retirement inventory](../../../evidence/revisions/cloud-offload-observer-bindings-20261125/retired-mirrors.json) retains exact hashes and the preservation boundary.
