# RGP-PB-01: Reuse RunFetcher to read saved run documents

The [patch](patches/verified-document-reader.patch) changes how VIPER reads saved
run documents before publishing them. It replaces the file-reading code in
`_RunGraphPromoter.read_local()` with a call to the existing
[`RunFetcher.read_verified()`](../../../src/viper/_source.py).

## Why this change comes first

The current [`read_local()`](../../../src/viper/execution/_promotion.py) reads a
file from local storage, then checks its size and SHA-256 against the recorded
values. `RunFetcher.read_verified()` already performs those checks and can also
read files from cloud storage. Reusing it removes the duplicate checks and
prepares the publisher to read the run documents we intend to move to Hugging Face.

For example, a reference to `run.yaml` records where the file is stored. It also
records the expected byte count and SHA-256. The fetcher retrieves the file and
checks its bytes against those values before returning them.

## What the patch changes

`promote_run_to_cloud()` already creates a `RunFetcher` to verify the source run.
The patch passes that same object into `_RunGraphPromoter`. Its new
`read_document()` method calls `fetcher.read_verified(reference)` and returns
the checked bytes. If the read fails, it raises `RunPromotionError` and keeps
the original exception as the cause.

The patch removes `read_local()` and updates every `_RunGraphPromoter`
constructor call to supply the new required argument. The public
`promote_run_to_cloud()` function still accepts only runs whose root record is
stored locally. Reading and rewriting a complete cloud-backed graph requires
the later changes in the [contract](../../../contracts/run-graph-republication.md).

The code review also checked nearby code for redundancy. `hashlib` remains in
use when identifying files for publication. `local_artifact_store` still reads
the snapshots being published. `_publish_sources()` is needed to stage files
from neighboring stores, and `source_identity()` hashes those files before
staging. The [export module's reader](../../../src/viper/execution/_export.py)
serves the separate archive-export path.

## Apply and validate

The patch is ready for you to apply. The source files in the active checkout
still contain the original implementation. From the repository root, apply
both file changes together:

```bash
rgp_patch=plans/run-graph-republication/RGP-PB-01/patches/verified-document-reader.patch
git apply --check "$rgp_patch" && git apply "$rgp_patch"
```

Activate the project's `.venv` and run Ruff's import fixes and formatter on the
two changed files. Then run the five `gate.steps` commands in
[plan.toml](plan.toml), in their listed order. Resolve any failure before
continuing to the next part of the migration.

The [recorded check results](../../../evidence/gates/rgp-pb-01-20261016-r3.json)
show 22 selected tests passing on the proposed patch. Pyright reported zero
errors and warnings. Ruff's documentation and lint checks passed, as did its
format check. These results belong to review commit
`a107a9f4e1832b0410d0d9e69e056d36939b10e2`.

The added tests check that the publisher uses the supplied fetcher. They also
check rejection of missing files and content mismatches. Existing promotion
tests passed alongside them. The cloud cases use simulated downloads; testing
transfers against live storage remains part of the later migration work.
