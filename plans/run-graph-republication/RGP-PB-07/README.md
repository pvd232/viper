# RGP-PB-07: Rehearse recovery and expose additional publications

Context: the copy must survive an interrupted upload and restore a model in a fresh process using the additional host. The public call also needs a separate process for its download caches and shared HTTP connections.

## Changes

`execution.promote_run_to_cloud()` keeps its three-argument return value. Supplying `RunPromotionPolicy.hosts` and `TransferLimits` starts a copy process and returns the additional references in host order, then run order. Several selected roots share one inventory and publication journal. Original roots and workspace settings remain intact.

`CopyRequest` records the selected roots, required files, target hosts, logical destination, limits, and approved source-code repositories. The worker discovers the graph, checks space, verifies the sources, publishes dependencies before parents, compares the saved graphs, and verifies the additional publication. It saves progress and comparison results before writing the final result.

`RunGraphPromoter` and `SnapshotCopy` now have ordinary names within their private modules because the worker and comparison code share them. The repository's import-boundary check covers those callers.

## Recovery checks

The connected test uses a saved numerical model, two roots sharing its dependencies, and a real Hugging Face provider with a controlled commit service. It loses the first commit response, resumes from that exact commit, compares the graphs, and checks the disk limit.

A separate Python process restores the copied model through ordinary readers, with fresh caches and original cloud reads rejected. On macOS, the test also uses the operating-system sandbox to deny reads from the original workspace and restrict network access to the controlled destination. A retained source dependency and a changed expected prediction each fail. Repairing the expected-result report reuses the saved prediction bytes.

The public-call test checks process inputs, target/root order, source preservation, and invalid worker responses. The complete repository fast check also covers reader, provider, retention, and access-boundary regressions. Exact commands and source hashes are recorded in review-checks.json after the checks finish.

## Remaining review boundary

Real model restoration and the complete saved prior/build inventory are exercised by PB-08. Independent human review remains pending. Original model training and full benchmark execution stay unchanged.
