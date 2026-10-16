# RGP-PB-01: Read saved run documents through RunFetcher

This directory records the completed reader change and the checks used to close
RGP-PB-01. The implementation is installed and committed.

## What is finished

[`RunFetcher`](../../../src/viper/_source.py) exposes `read()` and `path()`.
The subclass and verification flag are removed. Pre-existing artifacts are
checked once per execution; files published during that execution reuse the
hashes already computed for publication. Commit
[`27fbcaf8`](https://github.com/pvd232/viper/commit/27fbcaf8446cbeb2e76d8fee5717c43ce38006f8)
contains that change.

[`_RunGraphPromoter.read_document()`](../../../src/viper/execution/_promotion.py)
uses the same fetcher that checked the source run. Every constructor caller
supplies it. A failed read raises `RunPromotionError` with the original exception
as its cause. Commit
[`b1d5d9da`](https://github.com/pvd232/viper/commit/b1d5d9dab58c37524552c4e798282460080e7650)
contains the promoter change and its focused test. The public function still
requires a local root; cloud graph discovery belongs to RGP-PB-02.

## Files

| File | Purpose |
|---|---|
| [plan.toml](plan.toml) | Reproduces the installed promoter change from commit `27fbcaf8` and declares its checks. |
| [document-reader.patch](patches/document-reader.patch) | Exact promoter and test changes installed by `b1d5d9da`. |
| [Earlier patch](history/verified-document-reader.patch) | Superseded proposal, retained as history. Its old method names and extra tests are absent from the installed change. |

## Validation

The [completion gate](../../../evidence/gates/rgp-pb-01-completed.json) records
15 passing test cases in 21.42 seconds. It checks content reuse and rejection of
altered bytes through existing storage tests. Promotion tests cover fetcher
use, including a failed read, and existing publication behavior. This
documentation update reuses those tests.

The gate also passed Pyright and the source docstring check. Ruff's final format
and lint checks passed. The [implementation review](../../../evidence/reviews/rgp-pb-01-implementation.json)
confirms that the installed files match the tested candidate. The
[completion receipt](../../../evidence/lifecycle/rgp-pb-01-complete.json) closes
the block. Exact commands and outputs are retained in the gate receipt.

The earlier fetcher refactor passed 122 selected tests and four subtests, as
recorded in commit `27fbcaf8`. Full repository and release gates remain outside
this block's validation scope. Real model transfers await the later migration
blocks.

## Next step

[RGP-PB-02](../../../contracts/run-graph-republication.md#rgp-pb-02) will select
which storage to move and follow every dependency from a chosen run. Discovery
must include a document on Hugging Face that points back to GCS, so VIPER can
list every required file before copying anything.
