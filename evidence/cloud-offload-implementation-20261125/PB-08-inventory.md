# CFO-PB-08 destination inventory reuse

Parent: `c83af457`.

Independent destination comparison now registers its already checked complete
remote inventory through the shared registry. The resolver reuses that metadata
instead of fetching the same Hugging Face manifest twice. It registers no local
payload locations. Task-owned destination caches still download and verify remote
bytes independently of ordinary shared payloads.

All five existing manifest identity cases passed unchanged, including each
owner/workspace/revision/file-list rejection. Pyrefly and Ruff passed. Reviewer 04
approved the exact delta. Streaming cloud mocks and missing-file diagnostic text
are updated in the native integration fixture without removing its graph or
exception-chain assertions.

README example checks use immutable refs for file access. Their extended-program
aggregate budget accounts for multiple native runs and independent confirmation;
per-worker and single-command limits and numerical assertions are preserved.
The retained stack samples show existing cold interpreter/loader startup, not a
storage-lock wait. Completed checks and remaining integration outcomes are recorded
in the final validation evidence. This checkpoint does not claim final acceptance.
