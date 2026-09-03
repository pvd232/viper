# VIPER workday journal — September 3, 2026

## Outcome

Completed and published the first two post-foundation execution phases on
`codex/local-publication-downloads`. VIPER now has destination-neutral local
publication and runner-owned download stages. Both phases were checked through
the implemented Contract Traceability and System Impact workflow before their
commits were accepted.

## Completed work

### Execution environment

- Created the repository-local `.venv` from the package's declared
  `test,release` extras and used it for every project-owned command.
- Kept Conda outside the repository contract. A contributor may use Conda
  locally, but VIPER's documented commands now depend only on an activated
  Python environment.
- Set `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` for subprocess-heavy test runs
  on this macOS host to avoid the observed PyTorch fork crash.

### Master Phase 1 — local publication

- Added `StorageDestination`, `StorageSettings`, `SnapshotPublisher`, and
  `LocalSnapshotPublisher`.
- Added atomic run-destination binding and routed stage, attempt, invocation,
  and recovery publication through the selected publisher.
- Compiled the Phase 1 `ContractTraceabilityGraph`, compared the accepted
  baseline and candidate through CodeQL, passed the selected PairBlock gates,
  and accepted commit `a6e0bdd`.

### Master Phase 2 — runner-owned downloads

- Replaced the transport vocabulary with `HttpImplementationSpec`,
  `HttpContext`, `HttpResult`, `resolve_http()`, and `invoke_http()`.
- Made `DownloadSpec` runner-owned. Download stages no longer declare a
  project stage callable, parameter model, variant parameter record,
  `StageInvocationReceipt`, or `DownloadContext`.
- Added `publish_download_body()`. It copies into a temporary artifact sibling,
  checks the bytes and SHA-256 digest, and atomically installs the verified
  response at the declared artifact path.
- Made `ResolvedHttpRetrieval.body` and the same-named
  `ResolvedSingleFileArtifact.file` share one `SnapshotFileRef`.
- Moved project-process fields from `ResolvedBaseSpec` to
  `ResolvedParameterizedSpec` and removed the retired download worker path and
  `src/viper/paths.py`.
- Updated fixtures, generated projects, public protocol documentation, the
  Download Retrieval Artifacts contract, and the master checklist.
- Preserved the inherited Phase 1 execution-test identity and placed every
  Phase 2 implementation and verification edge inside its owning checklist
  PairBlock.

## Acceptance evidence

- System Impact checked 424 exact declaration targets with no failed targets,
  unexpected changes, or unsatisfied dependencies.
- All four Phase 2 PairBlock gates returned exit code 0.
- The accepted plan digest is
  `1133d266e37c08f9a30497f8f428b181aa668bfec51d76423232d99ef37b9269`.
- The acceptance receipt binds check
  `931a7700a81130b402dfe0a46eca81db3aef190fe35106c8052d26d335bbb9f5`
  to commit `50829466258f4dfd859e72e3009d014ee55af517`.
- The Contract Traceability and documentation boundary passed 82 tests.
- Ruff, Ruff formatting, Pyright, and Git whitespace checks passed over the
  changed boundary.
- The repository-wide suite was intentionally not run; change-aware focused
  gates covered the implemented phase.

## Next workday

Begin Master Phase 3 from accepted commit `5082946`: implement captured local
external roots under the External Input Roots contract. Before editing, update
that contract's live PairBlocks to the current `ContractTarget` protocol and
compile its selected `ContractTraceabilityGraph` against this accepted
baseline. Execute one accepted PairBlock at a time unless the reviewed contract
defines a single closed tranche.

The Download Retrieval Artifacts contract remains **In progress** only because
DRA-06 belongs to the coordinated public-documentation cleanup in Master Phase
11. No additional Phase 2 implementation work remains.
