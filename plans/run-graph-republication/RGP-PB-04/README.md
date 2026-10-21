# RGP-PB-04: Resume an interrupted publication

Context: an upload can finish before its response reaches VIPER. Saved progress must identify that commit before the next attempt writes anything.

## Implementation

`PublicationJournal` records the source snapshot, its files, the expected destination manifest, the child mappings, and the destination head observed before upload. It uses the existing canonical serializer and atomic file writer. A file lock admits one writer. Completed entries record an exact destination snapshot after every file passes a size and hash check.

`HuggingFaceProvider.find_publication()` checks commits after the recorded head and matches the complete expected manifest. An unresolved or ambiguous outcome stays pending. The journal requests one upload attempt through `ViperCloud.publish()`; ordinary callers retain the existing retry count. GCS recovery uses its content-addressed revision.

The promoter accepts an optional journal and supplies its source and child identities. The existing source and default storage settings remain unchanged.

## Review

Eleven focused cases passed. Pyright, docstring checks, and final Ruff checks passed. The tests cover successful copies, a lost commit response, repeated retries, changed requests, changed child bindings, and a second writer. Existing graph-publication and local-staging checks also passed. Exact commands and source hashes are in [review-checks.json](review-checks.json).

The Git commit and pull-request diff contain the source changes. Independent review remains pending. Later blocks supply resource controls and the end-to-end recovery rehearsal.

## Size

Production grows by 318 lines. Tests grow by 94 lines. The private progress record and writer replace restart-from-zero behavior and preserve completed remote work. The existing serializer, file writer, providers, and promoter remain the owners of their current work.
