# RGP-PB-02: List the files required by a run

Context: saved run records can link across local stores, GCS and Hugging Face.
The existing promoter now follows those links before copying artifacts.

## Changes

- Keep the one-field `RunPromotionPolicy.hosts` selected during pair coding.
- Expose cloud manifests through `RunFetcher.snapshot_files()`.
- Extend the promoter's existing discovery methods and file-address helper.
- Record each file's size and expected hash; local files may await a hash check.
- Check the required-file inventory and return snapshots in dependency order.
- Preserve ordinary local publication and all source files and settings.

The graph is represented by the promoter's existing document map plus file,
snapshot-membership, dependency, and active-read collections. Each collection
answers a separate question needed for complete discovery and cycle rejection.
The original broad installer and replica-reader proposal are excluded.

## Checks

The connected test graph contains a local root, an HF attempt record, and GCS
stage records and artifacts. It checks discovery with artifact downloads
blocked, repeated reads, missing required files, changed hashes and cycles.
The existing local-promotion tests exercise ordinary publication.

See `review-checks.json` for exact commands, outputs and source hashes.
This block is ready for independent review after its checks pass.

## Code growth

```text
9	2	src/viper/_source.py
219	77	src/viper/execution/_promotion.py
16	2	src/viper/storage.py
144	2	tests/test_run_execution.py
```
