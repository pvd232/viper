# Run Graph Republication

## 1. Status

**Contract status:** PB-01–PB-14 validation complete; PR review and integration pending.
The optimization blocks have retained checks and separate PRs. Their current
states are recorded below. The legacy compiler view is retained for historical
receipts; it does not update the new PR-backed blocks.

The [completion evidence](../evidence/run-graph-republication-completion-20261018.json)
records 783 completed mappings, zero pending mappings, all 1,305 required
payloads, four recovered models, and passing checks at VIPER `462b202` and RICO
`cd81561d`. Original GCS publications and canonical model pointers remain intact.

### PR review and integration

The migration's completed validation remains valid while its PRs await review
and merge. The generated `complete` and `bootstrap-complete` labels below
describe retained acceptance evidence. They do not establish GitHub approval or
integration into `main`. The current compiler does not ingest PR state.

GitHub observations refreshed on **2026-10-18 20:11 UTC**.
Validation, review, and integration are separate. Each local gate is bound to its
implementation commit through its PR and retained result; CI below describes only
the observed head. All observed PRs remain open without submitted reviews.

| Order | PairBlock contribution | PR | Observed head | Observed base branch | Validation | Review | Integration |
|---|---|---|---|---|---|---|---|
| 1 | PB-02 discovery | [VIPER #5](https://github.com/pvd232/viper/pull/5) | `c3ecfe262b6e88a2fccdb563e9b1f22ce552c4fc` | `main` | [7 passed](https://github.com/pvd232/viper/pull/5/checks) | Pending | Open; no merge commit |
| 2 | PB-03 publication | [VIPER #6](https://github.com/pvd232/viper/pull/6) | `62fb4764fbb1eab54b7f3fadec624e4daf3c2b7e` | `rgp/pb02-discovery-20261017` | [7 passed](https://github.com/pvd232/viper/pull/6/checks) | Pending | Open; no merge commit |
| 3 | PB-04 restart | [VIPER #7](https://github.com/pvd232/viper/pull/7) | `995785d9ff3b434362f238a08f7d1ca76dbf5508` | `rgp/pb03-publication-20261017` | [7 passed](https://github.com/pvd232/viper/pull/7/checks) | Pending | Open; no merge commit |
| 4 | PB-05 resources | [VIPER #8](https://github.com/pvd232/viper/pull/8) | `8a8788fd5a19130c7501829c4387db43c0359aa5` | `rgp/pb04-recovery-20261017` | [7 passed](https://github.com/pvd232/viper/pull/8/checks) | Pending | Open; no merge commit |
| 5 | PB-06 comparison | [VIPER #9](https://github.com/pvd232/viper/pull/9) | `f3c10aaead0ee3dfbaee17fb4e5155f98338788f` | `rgp/pb05-resources-20261017` | [7 passed](https://github.com/pvd232/viper/pull/9/checks) | Pending | Open; no merge commit |
| 6 | PB-07 rehearsal | [VIPER #10](https://github.com/pvd232/viper/pull/10) | `f98b694fc938a13ea746a0c7a63fdc9f8883c6f7` | `rgp/pb06-comparison-20261017` | [7 passed](https://github.com/pvd232/viper/pull/10/checks) | Pending | Open; no merge commit |
| 7 | PB-07 Pyrefly follow-up | [VIPER #11](https://github.com/pvd232/viper/pull/11) | `06fae367d03b5eca64b3a1910760a0e6c838493e` | `rgp/pb07-rehearsal-20261017` | [7 passed](https://github.com/pvd232/viper/pull/11/checks) | Pending | Open; no merge commit |
| 8 | PB-02 supporting inputs | [VIPER #12](https://github.com/pvd232/viper/pull/12) | `4fbe070d2c27eb3c9fd9521486ddc12d74739770` | `rgp/pb07-pyrefly-r2` | [7 passed](https://github.com/pvd232/viper/pull/12/checks) | Pending | Open; no merge commit |
| 9 | PB-04/05/06 recovery and verification follow-ups; PB-09–11 planning | [VIPER #13](https://github.com/pvd232/viper/pull/13) | `18794ae34eb259f93cc2d74b062ccd0a19ee013c` | `rgp/pb02-supporting-r2` | [7 passed](https://github.com/pvd232/viper/pull/13/checks) | Pending | Open; no merge commit |
| 10 | PB-08 publication and recovery | [RICO #26](https://github.com/pvd232/rico-rebuild/pull/26) | `cd81561d331f9d0a5fed7d16cc1892abffd0611a` | `main` | [1 passed](https://github.com/pvd232/rico-rebuild/pull/26/checks) | Pending | Open; no merge commit |
| 11 | PB-09 publication identities | [VIPER #14](https://github.com/pvd232/viper/pull/14) | `ef3d9dd56e351ea6ce19f7c24289cb710d2ddc9a` | `rgp/pb05-connection-reuse-r2` | [Local gates passed](../evidence/rgp-pb09-validation.json); [6 passed; 1 pending](https://github.com/pvd232/viper/pull/14/checks) | Pending | Open; no merge commit |
| 12 | PB-10 disk accounting | [VIPER #15](https://github.com/pvd232/viper/pull/15) | `d68a0411ecd3389672633b33ea4d16fed531de1e` | `rgp/pb09-prepared-publication` | [Local gates passed](../evidence/rgp-pb10-validation.json); [6 passed; 1 pending](https://github.com/pvd232/viper/pull/15/checks) | Pending | Open; no merge commit |
| 13 | PB-11 recovery reads | [RICO #27](https://github.com/pvd232/rico-rebuild/pull/27) | `0d2a4e78a43d1b4e79d3aba3d5157115288e9c85` | `rgp/model-publication-20261017` | [Local gates passed](https://github.com/pvd232/rico-rebuild/tree/rgp/pb11-recovery-reads/evidence/graph-publication-pb11); [1 passed](https://github.com/pvd232/rico-rebuild/pull/27/checks) | Pending | Open; no merge commit |
| 14 | PB-12 bounded verification cache | [VIPER #16](https://github.com/pvd232/viper/pull/16) | `c672a36caeafba5d96509182a212126035c99c33` | `rgp/pb10-single-space-scan` | [Local gates passed](../evidence/rgp-pb12-validation.json); [3 passed; 4 pending](https://github.com/pvd232/viper/pull/16/checks) | Pending | Open; no merge commit |
| 15 | PB-13 streaming metric hashes | [VIPER #17](https://github.com/pvd232/viper/pull/17) | `8c8aacf0698bc9ee05701e615b422d6538aa3318` | `rgp/pb12-retain-verification-cache` | [Local gates passed](../evidence/rgp-pb13-validation.json); [1 passed; 6 pending](https://github.com/pvd232/viper/pull/17/checks) | Pending | Open; no merge commit |
| 16 | PB-14 benchmark verification | [VIPER #18](https://github.com/pvd232/viper/pull/18) | `ca8fb352d0df90095fbbc2a0e29312dd8cdb282f` | `rgp/pb13-stream-metric-hashes` | [Local gates passed](../evidence/rgp-pb14-validation.json); [CI pending](https://github.com/pvd232/viper/pull/18/checks) | Pending | Open; no merge commit |

PB-01's accepted `8ae1631` is already an ancestor of VIPER `origin/main`; its
[historical review](../evidence/reviews/rgp-pb-01-implementation.json) and
[completion](../evidence/lifecycle/rgp-pb-01-complete.json) remain retained.
No separate PR is recorded for that block. PB-09, PB-10, and PB-11 have completed
local validation in #14, #15, and RICO #27 respectively. #13 retains their scope.

Review and merge VIPER **#5 → #6 → #7 → #8 → #9 → #10 → #11 → #12 → #13**,
then RICO **#26**. Continue with VIPER **#14 → #15** and RICO **#27**;
PB-11 can be reviewed independently of PB-09/10 after #26. Prefer **Create a merge commit**, which this repository allows,
to preserve the existing evidence and descendant commit identities. After each
VIPER merge, retarget the next PR to `main`, inspect the resulting diff, and
refresh required CI and review before merging. RICO #26 targets its own `main`;
integrate it after its VIPER dependency. Retain branches until any dependent PRs
have been retargeted and branch cleanup is separately authorized.

The executing agent automatically queries each linked PR with `gh pr view --json`
at workflow entry, after PR actions, and before reporting current status. Reuse
the shared skill's field selection and one observation per PR. Update this table
within the authorized edit cycle; after the final push, report fresh GitHub
state and retain it in the next edit cycle to avoid status-commit loops. While
the agent is idle, GitHub changes are observed on the next workflow entry.
Record the reviewer and reviewed SHA with the actual review URL or
user message reference. After merging, record the observed merge SHA, time, and
destination. Close without merge only for abandoned or superseded work, with
the reason and replacement PR. Such closure leaves integration incomplete and
preserves prior validation. The checklist links this table as its sole PR view.

GitHub documents [merge requirements and methods](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request),
[retargeting](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/changing-the-base-branch-of-a-pull-request),
and [closure without merge](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/closing-a-pull-request).

### Approved follow-ups

PB-12 retains bounded destination downloads; PB-13 streams metric hashes;
PB-14 reuses verification within benchmark execution and shares metric criteria.
All three passed local validation. Continue review and merge after #15 in order
**#16 → #17 → #18**; each PR targets its predecessor branch.
Their typed requirements are RGP-REQ-14–16. See the scoped
[PB-12](../plans/run-graph-republication/RGP-PB-12/README.md),
[PB-13](../plans/run-graph-republication/RGP-PB-13/README.md), and
[PB-14](../plans/run-graph-republication/RGP-PB-14/README.md) plans.
These append declarations without changing historical requirements or receipts.
No new cache format, persisted verification state, or publication is required.

<details>
<summary>Historical compiler view; use the PR table above for PB-09–11 status</summary>

<!-- contract-protocol:generated:start -->
**In progress.** [Jump to current PairBlock](#rgp-pb-09)

**Checklist:** [Run Graph Republication](../checklists/run-graph-republication.md)

### PairBlocks

<a id="rgp-pb-01"></a>

#### <nobr><code>RGP-PB-01</code></nobr>

**Status:** complete

**Requirement contribution:** Use one RunFetcher with read() and path(). Reuse content checks within each execution and pass the same fetcher into promotion.

**Review handoff**

**What changed**

- Pass the existing RunFetcher into promotion and call read() for saved run documents.
- Preserve the cause of a failed read and retain ordinary publication behavior.

**Plan deviations:** The shared RunFetcher was simplified in commit 27fbcaf8 before the promoter change in b1d5d9da. Existing storage tests cover hashing; one new promoter test covers delegation and failure.

**Start review:** [Open tested GitHub comparison](https://github.com/pvd232/viper/compare/b1d5d9dab58c37524552c4e798282460080e7650...5f0750153d866240e02ab725a0f079d22ec3bfde)

**Review these files**

- [Installed promoter change](../plans/run-graph-republication/RGP-PB-01/patches/document-reader.patch#L1)
- [Document reader](../src/viper/execution/_promotion.py#L103)
- [Reader and rejection tests](../tests/test_run_execution.py#L2187)

**Evidence:** [Passing gate receipt](../evidence/gates/rgp-pb-01-completed.json)

**Decision:** <nobr><code>RGP-PB-01</code></nobr> is complete; no further decision is required.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-01/plan.toml)

**Retained patch:** [patches/document-reader.patch](../plans/run-graph-republication/RGP-PB-01/patches/document-reader.patch)

**Implementation roots:** [pyproject.toml](../pyproject.toml) · [pyrightconfig.json](../pyrightconfig.json) · [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** None

**Gate steps:**

```bash
# typecheck
(cd . && pyright --pythonpath /Users/machina/Developer/ChatGPT/viper/.venv/bin/python src/viper/execution/_promotion.py tests/test_run_execution.py)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_run_execution.py::test_promotion_document_reader_uses_fetcher tests/test_run_execution.py::test_cloud_promotion_stages_verified_neighboring_store 'tests/test_run_execution.py::test_explicit_cloud_promotion_preserves_local_run_mode[False]' tests/test_storage.py::test_new_execution_checks_a_previously_read_local_file tests/test_storage.py::test_run_fetcher_checks_download_once_before_caching tests/test_storage.py::test_run_fetcher_shares_first_content_check_between_read_and_path tests/test_storage.py::test_local_publication_reuses_hashes_and_preserves_revision)
# documentation
(cd . && ruff check --config pyproject.toml --select D src/viper tests)
# lint
(cd . && ruff format --check --config pyproject.toml src/viper/execution/_promotion.py tests/test_run_execution.py)
# lint
(cd . && ruff check --config pyproject.toml src/viper/execution/_promotion.py tests/test_run_execution.py)
```

</details>

<a id="rgp-pb-02"></a>

#### <nobr><code>RGP-PB-02</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Bind original sources independently of the destination and discover every required dependency before publication.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-02 implementation at 2bb68454e92ba04d16fbbb5d015224552ac6fc60.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-02/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-02/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-02/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-02/patches/implementation.patch)

**Implementation roots:** [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>RGP-PB-01</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check src/viper tests)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_run_execution.py::test_promotion_discovers_mixed_cloud_ancestors tests/test_run_execution.py::test_promotion_rejects_missing_legacy_settings tests/test_run_execution.py::test_promotion_document_reader_uses_fetcher tests/test_run_execution.py::test_cloud_promotion_stages_verified_neighboring_store 'tests/test_run_execution.py::test_explicit_cloud_promotion_preserves_local_run_mode[False]')
# documentation
(cd . && ruff check --select D src/viper tests)
# lint
(cd . && ruff format --check src/viper/_source.py src/viper/execution/_promotion.py src/viper/storage.py tests/test_run_execution.py)
# lint
(cd . && ruff check src/viper/_source.py src/viper/execution/_promotion.py src/viper/storage.py tests/test_run_execution.py)
```

</details>

<a id="rgp-pb-03"></a>

#### <nobr><code>RGP-PB-03</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Republish cloud snapshots while preserving payload bytes and every mapped provenance relationship.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-03 implementation at 2151d6665880ab37e4bb5ad4793525cf599e6975.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-03/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-03/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-03/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-03/patches/implementation.patch)

**Implementation roots:** [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>RGP-PB-02</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check src/viper tests)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_run_execution.py::test_republication_preserves_files_and_follows_new_references tests/test_run_execution.py::test_promotion_discovers_mixed_cloud_ancestors tests/test_run_execution.py::test_cloud_promotion_stages_verified_neighboring_store 'tests/test_run_execution.py::test_explicit_cloud_promotion_preserves_local_run_mode[False]' tests/test_run_execution.py::test_cloud_promotion_rebinds_reuse_key_for_stored_pointer)
# documentation
(cd . && ruff check --select D src/viper tests)
# lint
(cd . && ruff format --check src/viper/execution/_promotion.py tests/fixtures.py tests/test_run_execution.py)
# lint
(cd . && ruff check src/viper/execution/_promotion.py tests/fixtures.py tests/test_run_execution.py)
```

</details>

<a id="rgp-pb-04"></a>

#### <nobr><code>RGP-PB-04</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Persist publication intents and verified bindings; recover uncertain commits and share ancestors across restarts.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-04 implementation at f9817194faa83c495aef9355db93c103b77876a2.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-04/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-04/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-04/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-04/patches/implementation.patch)

**Implementation roots:** [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>RGP-PB-03</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check src/viper tests)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_cloud_service.py tests/test_run_execution.py::test_republication_preserves_files_and_follows_new_references tests/test_run_execution.py::test_cloud_promotion_stages_verified_neighboring_store)
# documentation
(cd . && ruff check --select D src/viper tests)
# lint
(cd . && ruff format --check src/viper/cloud.py src/viper/execution/_promotion.py src/viper/execution/_promotion_journal.py src/viper/huggingface.py tests/fixtures.py tests/test_cloud_service.py)
# lint
(cd . && ruff check src/viper/cloud.py src/viper/execution/_promotion.py src/viper/execution/_promotion_journal.py src/viper/huggingface.py tests/fixtures.py tests/test_cloud_service.py)
```

</details>

<a id="rgp-pb-05"></a>

#### <nobr><code>RGP-PB-05</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Enforce measured transfer budgets and reclaim only task-owned disposable files after verified publication.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-05 implementation at 97cadc32fd7c640a48942933ef24b5e6f052bd54.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-05/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-05/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-05/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-05/patches/implementation.patch)

**Implementation roots:** [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>RGP-PB-04</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check src/viper tests)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_cloud_service.py tests/test_retention.py tests/test_storage.py tests/test_run_execution.py::test_republication_obeys_resource_limits tests/test_run_execution.py::test_promotion_discovers_mixed_cloud_ancestors tests/test_run_execution.py::test_republication_preserves_files_and_follows_new_references)
# documentation
(cd . && ruff check --select D src/viper tests)
# lint
(cd . && ruff format --check src/viper/_source.py src/viper/execution/_promotion.py src/viper/execution/_promotion_journal.py src/viper/execution/_promotion_transfer.py src/viper/huggingface.py tests/fixtures.py tests/test_cloud_service.py tests/test_retention.py tests/test_run_execution.py)
# lint
(cd . && ruff check src/viper/_source.py src/viper/execution/_promotion.py src/viper/execution/_promotion_journal.py src/viper/execution/_promotion_transfer.py src/viper/huggingface.py tests/fixtures.py tests/test_cloud_service.py tests/test_retention.py tests/test_run_execution.py)
```

</details>

<a id="rgp-pb-06"></a>

#### <nobr><code>RGP-PB-06</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Independently compare original and rewritten graphs against the frozen inventory and exact mapping.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-06 implementation at 293628b25f5fc313d85c8faf00772753d509c7a0.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-06/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-06/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-06/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-06/patches/implementation.patch)

**Implementation roots:** [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>RGP-PB-05</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check src/viper tests)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_run_execution.py::test_republication_compares_source_and_destination tests/test_run_execution.py::test_republication_obeys_resource_limits tests/test_run_execution.py::test_republication_preserves_files_and_follows_new_references tests/test_cloud_service.py)
# documentation
(cd . && ruff check --select D src/viper tests)
# lint
(cd . && ruff format --check src/viper/execution/_promotion_compare.py src/viper/execution/_promotion_transfer.py tests/test_run_execution.py)
# lint
(cd . && ruff check src/viper/execution/_promotion_compare.py src/viper/execution/_promotion_transfer.py tests/test_run_execution.py)
```

</details>

<a id="rgp-pb-07"></a>

#### <nobr><code>RGP-PB-07</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Prove small-graph restart recovery and cold model loading with Mantra unavailable and bounded inference.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-07 implementation at f98b694fc938a13ea746a0c7a63fdc9f8883c6f7.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-07/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-07/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-07/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-07/patches/implementation.patch)

**Implementation roots:** [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>RGP-PB-06</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check src/viper tests)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_cloud_service.py tests/test_run_execution.py::test_copy_worker_resumes_and_restores_a_model tests/test_run_execution.py::test_republication_compares_source_and_destination tests/test_retention.py tests/test_validation_architecture.py::test_source_tree_uses_one_private_boundary)
# documentation
(cd . && ruff check --select D src/viper tests)
# lint
(cd . && ruff format --check src/viper/execution/__init__.py src/viper/execution/_promotion.py src/viper/execution/_promotion_compare.py src/viper/execution/_promotion_journal.py src/viper/execution/_promotion_transfer.py src/viper/execution/_promotion_worker.py src/viper/storage.py tests/fixtures.py tests/test_cloud_service.py tests/test_run_execution.py)
# lint
(cd . && ruff check src/viper/execution/__init__.py src/viper/execution/_promotion.py src/viper/execution/_promotion_compare.py src/viper/execution/_promotion_journal.py src/viper/execution/_promotion_transfer.py src/viper/execution/_promotion_worker.py src/viper/storage.py tests/fixtures.py tests/test_cloud_service.py tests/test_run_execution.py)
```

</details>

<a id="rgp-pb-08"></a>

#### <nobr><code>RGP-PB-08</code></nobr>

**Status:** bootstrap-complete

**Requirement contribution:** Register the completed additional publication after all four model recoveries pass, preserving original source objects and canonical model pointers.

**Review handoff**

**What changed**

- Retain the completed RGP-PB-08 implementation at cd81561d331f9d0a5fed7d16cc1892abffd0611a.

**Plan deviations:** Historical plan reconstructed on 2026-10-18 from the retained implementation commit. Existing review-checks and migration acceptance record the executed checks; reconstruction does not claim a new gate run.

**Start work:** [Open current plan](../plans/run-graph-republication/RGP-PB-08/plan.toml)

**Review these files**

- [Retained implementation diff](../plans/run-graph-republication/RGP-PB-08/patches/implementation.patch#L1)

**Evidence:** No passing gate receipt.

**Decision:** No lifecycle action is required for accepted bootstrap history.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/run-graph-republication/RGP-PB-08/plan.toml)

**Retained patch:** [patches/implementation.patch](../plans/run-graph-republication/RGP-PB-08/patches/implementation.patch)

**Implementation roots:** [tools/graph_publication](../../rico-publication-20261017/tools/graph_publication)

**Test roots:** [tests/test_graph_publication.py](../../rico-publication-20261017/tests/test_graph_publication.py)

**Dependencies:** <nobr><code>RGP-PB-07</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyrefly check tools/graph_publication tests/test_graph_publication.py)
# test
(cd . && python3 -m pytest -q tests/test_graph_publication.py)
# documentation
(cd . && ruff check --select D tools/graph_publication tests/test_graph_publication.py)
# lint
(cd . && ruff format --check tests/test_graph_publication.py tools/graph_publication/README.md tools/graph_publication/checks.py tools/graph_publication/prepare.py tools/graph_publication/publish.py tools/graph_publication/recover.py)
# lint
(cd . && ruff check tests/test_graph_publication.py tools/graph_publication/README.md tools/graph_publication/checks.py tools/graph_publication/prepare.py tools/graph_publication/publish.py tools/graph_publication/recover.py)
```

</details>

<a id="rgp-pb-09"></a>

#### <nobr><code>RGP-PB-09</code></nobr>

**Status:** drafting

**Requirement contribution:** Reuse prepared upload identities and one complete HF manifest per verification site.

**Plan:** None

**Current receipt:** None

**Dependencies:** <nobr><code>RGP-PB-08</code></nobr>

**Next action:** Run the current PairBlock plan.

<a id="rgp-pb-10"></a>

#### <nobr><code>RGP-PB-10</code></nobr>

**Status:** waiting

**Requirement contribution:** Measure staging and cache usage together while preserving both resource boundaries.

**Plan:** None

**Current receipt:** None

**Dependencies:** <nobr><code>RGP-PB-09</code></nobr>

**Next action:** Wait for the declared dependencies.

<a id="rgp-pb-11"></a>

#### <nobr><code>RGP-PB-11</code></nobr>

**Status:** drafting

**Requirement contribution:** Reuse request bytes and pointer digests within each recovery-tool invocation.

**Plan:** None

**Current receipt:** None

**Dependencies:** <nobr><code>RGP-PB-08</code></nobr>

**Next action:** Run the current PairBlock plan.


### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>RGP-REQ-01</code></nobr> | The promoter must read identified protocol documents through its supplied RunFetcher.read(). RunFetcher.path() supplies file paths for payloads. One RunFetcher must check pre-existing artifacts once per execution and reuse hashes for files published during that execution. Local, GCS, and Hugging Face reads must enforce the recorded byte count and SHA-256. Every ordinary retrieval or verification exception must become RunPromotionError("source run graph is unavailable") with the original exception as its cause. RGP-PB-01 retains the public local-root restriction and existing publication behavior. | complete | <nobr><code>RGP-VR-01</code></nobr> | <nobr><code>RGP-PB-01</code></nobr> |
| <nobr><code>RGP-REQ-02</code></nobr> | RunPromotionPolicy.hosts names the destination cloud repositories for additional graph publications. Original files, references, workspace settings, and canonical SOTA pointers remain unchanged. Source readers resolve provider-specific addresses directly and obtain older viper_cloud addresses from the original workspace configuration. Missing source settings fail before publication. Transfer budgets belong to the transfer operation. | complete | <nobr><code>RGP-VR-02</code></nobr> | <nobr><code>RGP-PB-02</code></nobr> |
| <nobr><code>RGP-REQ-03</code></nobr> | Discovery follows typed documents across local, GCS, Hugging Face, and pinned Git storage. It lists every member of the required snapshots before transferring artifacts, checks a separately frozen required-file inventory, rejects conflicting identities and dependency cycles, and records pending hashes for additional local files. Shared ancestors keep every source relationship. HF documents that refer to GCS files remain part of the discovered graph. | complete | <nobr><code>RGP-VR-03</code></nobr> | <nobr><code>RGP-PB-02</code></nobr> |
| <nobr><code>RGP-REQ-04</code></nobr> | Publication must keep every scientific payload byte-identical and rewrite only identified protocol references and the metadata identities derived from those changes. Preserve stage identities, code commits, parameters, input roles, measurements, and provenance relationships. Update run-plan stage hashes, reuse keys, source-closure links, and cloud-stage references together. Key graph mappings by complete source identity; shared payload hashes must never collapse distinct producing histories. Preserve sealed snapshot membership and reject inconsistent identities. | complete | <nobr><code>RGP-VR-04</code></nobr> | <nobr><code>RGP-PB-03</code></nobr> |
| <nobr><code>RGP-REQ-05</code></nobr> | Before remote publication, persist an intent bound to the source snapshot, destination, policy digest, expected rewritten manifest, and dependency bindings. Recover the exact verified destination commit after interruption, including a lost response after a successful commit. Publish the completed binding atomically only after verifying that commit. Reuse completed bindings across selected roots and process restarts. Serialize writers for the same publication journal; reject mismatched or corrupt state. Reconcile an uncertain remote outcome before retrying and fail closed when its identity cannot be established. Retain completed children when a parent fails. | complete | <nobr><code>RGP-VR-05</code></nobr> | <nobr><code>RGP-PB-04</code></nobr> |
| <nobr><code>RGP-REQ-06</code></nobr> | Preflight must measure selected snapshots and available staging capacity before payload verification or transfer. Path-backed payload reads, source verification, publication, and destination verification must obey explicit staging, cache, and connection limits. Count VIPER, Hugging Face, and Xet caches and cross-filesystem copies. Persist verified destination bindings before reclaiming task-owned staged files. A snapshot that cannot fit the declared budget must fail before transfer; all unmodified source bytes and shared caches remain intact. Retry and cancellation must leave recoverable evidence and bounded temporary storage. | complete | <nobr><code>RGP-VR-06</code></nobr> | <nobr><code>RGP-PB-05</code></nobr> |
| <nobr><code>RGP-REQ-07</code></nobr> | A verifier independent of the rewriting traversal must compare the source and destination graphs using the saved mapping and the frozen inventory. Require exact scientific payload hashes, exact required inventory membership, preserved non-location fields, and an explicit field-level allowlist of derived metadata changes. Every original dependency edge must reach its intended mapped destination object. Reject missing, extra, altered, or substituted required objects even when the destination graph passes ordinary verification. Record the source roots, destination roots, inventory digest, policy digest, mapping digest, and comparison result. | complete | <nobr><code>RGP-VR-07</code></nobr> | <nobr><code>RGP-PB-06</code></nobr> |
| <nobr><code>RGP-REQ-08</code></nobr> | Acceptance must run ordinary VIPER readers and model loading in a new process and fresh workspace with empty VIPER, Hugging Face, and Xet caches, no source store mounts, and original Mantra storage blocked. Allow only declared pinned external source repositories and the destination. Restore each selected model and run one frozen inference fixture under its recorded environment; compare against a retained expected result with a predeclared exact or numerical comparison rule. Persist inference output before downstream reporting so reporting repair reuses the measurement. Retain existing training and evaluation evidence without rerunning those experiments. | complete | <nobr><code>RGP-VR-08</code></nobr> | <nobr><code>RGP-PB-07</code></nobr> |
| <nobr><code>RGP-REQ-09</code></nobr> | Before bulk migration, a small mixed local/GCS/Hugging Face graph with two roots, a shared ancestor, distinct histories sharing payload bytes, and a reuse receipt must pass discovery, publication, restart recovery, independent comparison, and cold model recovery. Interrupt after a remotely committed child before its local acknowledgement and verify restart reuses that exact child. Record actual memory, disk, and connection observations. Preserve ordinary promotion tests and reject early public cloud-root enablement until the complete path passes. | complete | <nobr><code>RGP-VR-09</code></nobr> | <nobr><code>RGP-PB-07</code></nobr> |
| <nobr><code>RGP-REQ-10</code></nobr> | Publish the frozen MIL and Hopfield roots to an additional host, preserve source-to-destination mappings and the required-file inventory, and register the accepted publication atomically after all four models pass isolated recovery and frozen inference. Preserve original GCS publications, canonical model pointers, and default storage configuration. | complete | <nobr><code>RGP-VR-10</code></nobr> | <nobr><code>RGP-PB-08</code></nobr> |
| <nobr><code>RGP-REQ-11</code></nobr> | Reuse the journal-prepared SnapshotFileRef tuple and RevisionManifest when publishing unchanged staged inputs through the existing provider.publish_revision() path. Hash each upload input once in VIPER per publication attempt; preserve first-use checks, root confinement, intent-before-upload, exact-commit recovery, and destination byte readback before completion. Each HF journal check and graph-comparison snapshot check reads its complete manifest once, retaining complete owner/workspace/revision/files equality and generic-provider inventory checks. | in_progress | <nobr><code>RGP-VR-11</code></nobr> | <nobr><code>RGP-PB-09</code></nobr> |
| <nobr><code>RGP-REQ-12</code></nobr> | Compute staging and nested-cache usage in one filesystem traversal per TransferSpace.check(). Preserve independent inode sets and symlink-confinement boundaries for both budgets, temporary-file accounting, peak observations, early reservation failures, and task-owned cleanup. Compare identical trees and report traversal counts and measured duration separately. | planned | <nobr><code>RGP-VR-12</code></nobr> | <nobr><code>RGP-PB-10</code></nobr> |
| <nobr><code>RGP-REQ-13</code></nobr> | Within one RICO preparation or registration invocation, read each recovery request and model pointer once where its parsed value and digest are reused. Derive both from the same bytes. Preserve exact saved addresses, full journal membership, per-invocation pointer/request/prediction integrity checks, all-four-model coverage, and saved inference reuse. | in_progress | <nobr><code>RGP-VR-13</code></nobr> | <nobr><code>RGP-PB-11</code></nobr> |

### Verification rules

| Rule | Requirements | Acceptance conditions | Success case | Rejection cases |
|---|---|---|---|---|
| <nobr><code>RGP-VR-01</code></nobr> | <nobr><code>RGP-REQ-01</code></nobr> | The promoter calls the supplied fetcher's read() method and returns its bytes.<br>A failed document read raises the exact public message and preserves the original cause.<br>The fetcher rejects altered content and checks pre-existing artifacts again in a new execution.<br>Ordinary local promotion and staging from neighboring stores retain their existing behavior. | [test_promotion_document_reader_uses_fetcher](../tests/test_run_execution.py) | [test_promotion_document_reader_uses_fetcher](../tests/test_run_execution.py)<br>[test_new_execution_checks_a_previously_read_local_file](../tests/test_storage.py)<br>[test_run_fetcher_checks_download_once_before_caching](../tests/test_storage.py) |
| <nobr><code>RGP-VR-02</code></nobr> | <nobr><code>RGP-REQ-02</code></nobr> | The same source graph resolves after the destination is changed to Hugging Face.<br>RunPromotionError contains "legacy source binding is required" for an unbound provider-neutral source.<br>RunPromotionError contains "unclassified graph dependency" for required storage outside the explicit policy; no publication occurs. | [test_promotion_discovers_mixed_cloud_ancestors](../tests/test_run_execution.py) | [test_promotion_rejects_missing_legacy_settings](../tests/test_run_execution.py) |
| <nobr><code>RGP-VR-03</code></nobr> | <nobr><code>RGP-REQ-03</code></nobr> | A Hugging Face parent pointing to a GCS prior is traversed and rewritten.<br>RunPromotionError contains "inventory item is unreachable" when a required inventory entry has no graph binding.<br>RunPromotionError contains "storage cycle" for cyclic snapshot dependencies. | [test_promotion_discovers_mixed_cloud_ancestors](../tests/test_run_execution.py) | [test_republication_compares_source_and_destination](../tests/test_run_execution.py) |
| <nobr><code>RGP-VR-04</code></nobr> | <nobr><code>RGP-REQ-04</code></nobr> | Two producers with identical payloads retain distinct mapped records and consumer edges.<br>RunPromotionError contains "conflicting source identity" for two identities asserted for the same source object.<br>An independently valid substitute ancestor is rejected with "graph relationship changed". | [test_republication_preserves_files_and_follows_new_references](../tests/test_run_execution.py) | [test_republication_compares_source_and_destination](../tests/test_run_execution.py) |
| <nobr><code>RGP-VR-05</code></nobr> | <nobr><code>RGP-REQ-05</code></nobr> | Inject interruption before and after every persistent write and remote commit boundary; recovered references equal the uninterrupted binding.<br>A second selected root uses the already-verified shared ancestor binding.<br>RunPromotionError contains "publication journal differs", "remote publication outcome is unresolved", or "publication journal is locked" for the corresponding rejection. | [test_republication_recovers_commit_after_lost_response](../tests/test_cloud_service.py) | [test_republication_keeps_an_uncertain_write_pending](../tests/test_cloud_service.py)<br>[test_republication_recovers_commit_after_lost_response](../tests/test_cloud_service.py) |
| <nobr><code>RGP-VR-06</code></nobr> | <nobr><code>RGP-REQ-06</code></nobr> | Measured peak staging bytes, cache bytes, and concurrent connections stay within the supplied policy.<br>RunPromotionError contains "staging budget is insufficient" before a payload download when the snapshot cannot fit.<br>Injected transfer failure releases only task-owned disposable files and retains the journal and verified destination bindings. | [test_republication_obeys_resource_limits](../tests/test_run_execution.py) | [test_transfer_space_checks_capacity_and_preserves_source_files](../tests/test_cloud_service.py)<br>[test_directory_bytes_rejects_links_outside_the_copy](../tests/test_cloud_service.py) |
| <nobr><code>RGP-VR-07</code></nobr> | <nobr><code>RGP-REQ-07</code></nobr> | Comparison accepts only location changes and their declared derived identities.<br>RunPromotionError contains "graph relationship changed" for the wrong valid ancestor.<br>RunPromotionError contains "unexpected metadata change" for altered parameters, code identity, roles, or measurements. | [test_republication_compares_source_and_destination](../tests/test_run_execution.py) | [test_republication_compares_source_and_destination](../tests/test_run_execution.py) |
| <nobr><code>RGP-VR-08</code></nobr> | <nobr><code>RGP-REQ-08</code></nobr> | A fresh process restores the model and produces the expected bounded inference result using only permitted endpoints.<br>A deliberately retained Mantra dependency causes an observed blocked read and failed acceptance.<br>A changed output fails the fixture comparison; rerunning a report reuses the immutable inference output. | [test_copy_worker_resumes_and_restores_a_model](../tests/test_run_execution.py) | [test_copy_worker_resumes_and_restores_a_model](../tests/test_run_execution.py) |
| <nobr><code>RGP-VR-09</code></nobr> | <nobr><code>RGP-REQ-09</code></nobr> | One retained rehearsal receipt binds all stages and measured resource peaks.<br>A missing prior or donor dependency fails before any canonical pointer is updated. | [test_copy_worker_resumes_and_restores_a_model](../tests/test_run_execution.py) | [test_copy_worker_resumes_and_restores_a_model](../tests/test_run_execution.py) |
| <nobr><code>RGP-VR-10</code></nobr> | <nobr><code>RGP-REQ-10</code></nobr> | Registration requires every selected source root and a passing graph comparison covering the frozen inventory.<br>Registration rejects changed original model pointers, missing model reports, changed prediction bytes, or requests that differ from their retained reports.<br>The retained real publication contains 1305 required payloads and four exact model-recovery results; original source pointers remain unchanged. | [test_registration_requires_all_selected_models](../../rico-publication-20261017/tests/test_graph_publication.py) | [test_registration_requires_all_selected_models](../../rico-publication-20261017/tests/test_graph_publication.py)<br>[test_recovery_rejects_original_storage](../../rico-publication-20261017/tests/test_graph_publication.py) |
| <nobr><code>RGP-VR-11</code></nobr> | <nobr><code>RGP-REQ-11</code></nobr> | A path-backed upload invokes VIPER source_file once and both HF verification sites invoke read_manifest once per snapshot; ordinary public publish still hashes its own sources.<br>Changed upload bytes fail destination readback with ViperCloudError containing file identity changed and leave the journal binding pending; an out-of-root source remains rejected.<br>Lost-response recovery retains the exact commit; manifest owner/workspace/revision/file mutations raise RunPromotionError containing destination snapshot differs. | [test_republication_reuses_prepared_identities](../tests/test_cloud_service.py) | [test_republication_reuses_prepared_identities](../tests/test_cloud_service.py)<br>[test_republication_reads_manifest_once](../tests/test_run_execution.py)<br>[test_republication_recovers_commit_after_lost_response](../tests/test_cloud_service.py) |
| <nobr><code>RGP-VR-12</code></nobr> | <nobr><code>RGP-REQ-12</code></nobr> | A scan counter observes one visit per real directory while returned staging and cache totals match the original two-pass computation on the same tree.<br>Cross-boundary hard links contribute once to each applicable budget; internal file symlinks remain counted and directory symlinks remain untraversed.<br>Escaping cache or staging symlinks raise RunPromotionError containing cached file escapes; insufficient reservations retain the existing budget messages and occur before transfer. | [test_transfer_space_scans_both_budgets_once](../tests/test_cloud_service.py) | [test_transfer_space_scans_both_budgets_once](../tests/test_cloud_service.py)<br>[test_transfer_space_checks_capacity_and_preserves_source_files](../tests/test_cloud_service.py) |
| <nobr><code>RGP-VR-13</code></nobr> | <nobr><code>RGP-REQ-13</code></nobr> | Count one request-byte read per request and one pointer digest per distinct model pointer per invocation; generated requests and registration bytes equal the baseline.<br>Changed pointers, report bindings, predictions, or saved addresses retain their current ValueError rejection; saved predictions keep identical bytes and modification times. | [test_registration_reuses_request_and_pointer_reads](../../rico-publication-20261017/tests/test_graph_publication.py) | [test_registration_requires_all_selected_models](../../rico-publication-20261017/tests/test_graph_publication.py)<br>[test_model_checks_preserve_valid_saved_addresses](../../rico-publication-20261017/tests/test_graph_publication.py) |
<!-- contract-protocol:generated:end -->

</details>

## 2. Claim

VIPER publishes the complete selected graph to an additional host with unchanged
scientific payloads and provenance relationships, recovers the selected models
using that host alone, and reuses verified work within the declared resource limits.

The [typed declaration](run-graph-republication.toml) owns requirements and
verifier conditions. RGP-REQ-11 through RGP-REQ-16 govern the implemented optimization
work; the completed migration requirements remain the compatibility boundary.

## Implemented changes

The [impact analysis](run-graph-republication-optimization-impact.md) retains the
baseline diagrams, removal decisions, measured counts, and timing limits.
PB-09–14 reuse prepared publication identities, complete manifests, disk scans,
recovery requests, destination downloads, and benchmark checks. Metric workers
stream file hashes. The [PR table](#pr-review-and-integration) records validation
separately from review and integration.

## 3. Models

| Existing record | Writer, consumer, and retained role |
|---|---|
| `SnapshotFileRef` | `source_file` writes path, SHA-256, and byte count; the journal and provider reuse the same identities. |
| `RevisionManifest` | The journal computes owner, workspace, revision, and files; provider publication and destination verification consume it. |
| `SnapshotCopy` | The journal saves expected files before upload and the exact published commit after readback. |
| `TransferLimits` | The caller supplies staging/cache bytes and connections; `TransferSpace` enforces them. |
| Recovery request and prediction | RICO reads fixed addresses and settings, preserves inference output, and validates the same request/report binding during registration. |

The extension preserves the existing public models, serialized variants, and cache ownership.

## 4. Execution

Publication reuses prepared identities and complete manifest checks. Capacity
checks count both budgets in one traversal. Independent comparison retains
destination downloads until a reservation requires cleanup; semantic verification
reuses the retained files. RICO reuses request bytes and pointer digests.
Metric workers still check their own input bytes, using bounded-memory hashes.
Benchmark execution reuses its candidate and confirmation-stage checks while
public verification independently checks supplied results.

## 5. Persisted evidence

| Record | Purpose |
|---|---|
| [Completion evidence](../evidence/run-graph-republication-completion-20261018.json) | Pinned CI results, exact publication acceptance identity, four recovery results, and historical scan observations. |
| [Declaration revision](../evidence/revisions/rgp-optimization-plan.json) | Exact prior and candidate packages with the computed affected block set. |
| [Historical plans](../plans/run-graph-republication/) | Retained Git implementation patches and declared checks for completed blocks. Newly reconstructed plans explicitly identify their reconstruction. |
| PR diffs and retained validation results | Git retains new implementation bytes; the PR table links the tested changes, check results, review, and integration separately. |

## 6. Verification

The typed verifiers name observing tests for every block. Each new block's
planning note and validation result record its checks and rejection cases. The
protected generated table retains the historical declaration. Use Pyrefly, affected tests, discovered documentation checks, then
non-mutating Ruff format and lint checks after target-path import/format repair.

Contract-only changes use typed package/workspace/revision/compiled-state checks,
verifier-symbol checks, relative-link checks, and diagram rendering. Production
regressions and live model recovery are reserved for changes that reach those
boundaries; existing completed measurements remain retained.

## 7. Propagation

The [removal map](run-graph-republication-optimization-impact.md#propagation-and-removal-map)
assigns every changed, retained, and proposed surface to its requirement and block.

## 8. Acceptance case

### Success

For one path-backed `weights.bin`, the journal computes its identity once,
saves the expected manifest, and gives the existing provider that identity.
After exact-commit publication, one full HF manifest comparison and ordinary
byte readback establish the saved binding. Independent comparison preserves
both histories when two producers share those payload bytes.

### Rejection

If `weights.bin` changes after preparation, destination readback raises
`ViperCloudError` containing `file identity changed`; the journal retains a pending
binding. A substituted valid ancestor still raises `RunPromotionError` containing
`graph relationship changed`. Both staging and cache symlink escapes remain rejected.

## 9. Implementation order

Validation for PB-01–14 is complete. Review the dependency stack in the order
recorded above, continuing **#16 → #17 → #18** after #15. Each new block has its
own PR. Review and merge remain pending; integrate dependencies first when
merging is authorized.

## 10. Contract-owned PairBlocks

- [RGP-PB-09](../plans/run-graph-republication/RGP-PB-09/README.md): reuse upload identities and HF manifests.
- [RGP-PB-10](../plans/run-graph-republication/RGP-PB-10/README.md): count both disk budgets in one traversal.
- [RGP-PB-11](../plans/run-graph-republication/RGP-PB-11/README.md): reuse RICO request bytes and pointer digests.
- [RGP-PB-12](../plans/run-graph-republication/RGP-PB-12/README.md): retain bounded destination downloads.
- [RGP-PB-13](../plans/run-graph-republication/RGP-PB-13/README.md): stream metric dependency hashes.
- [RGP-PB-14](../plans/run-graph-republication/RGP-PB-14/README.md): reuse benchmark verification and share metric criteria.

## 11. ContractTarget

The current extension declares scope and observing checks. Edit the named real
repository paths, run the focused gate, commit and push, and create the linked
PR. Preserve the tested SHA and results, actual review decision, and observed
merge separately. Git and the PR diff retain implementation bytes; new blocks
need no saved patch payload. Existing plans remain historical evidence. A
missing implementation or failed gate leaves new validation pending while
completed migration evidence remains valid.

## Remaining measurement

[The implemented follow-ups](run-graph-republication-optimization-impact.md#implemented-follow-ups-pb-1214)
have measured operation counts and a local hashing benchmark. Production network
and full benchmark wall-time savings remain unmeasured; completed publication
and scientific measurements were preserved.
