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
- Early Phase 1 and Phase 2 test runs used
  `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` after macOS reported a child-side
  pre-exec crash. The child-process hardening work below removed that
  workaround from the final acceptance boundary.

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

### macOS child-process hardening

- Promoted the deferred crash TODO into the
  [Child-process launching](../docs/development/child-process-launching.md)
  contract with requirements `CPL-01` and `CPL-02`, PairBlocks `P2-CPL-01`
  and `P2-CPL-02`, exact `ContractTarget` declarations, and checklist edges.
- Traced five Python crash reports to `_posixsubprocess.fork_exec()`. Four
  reports came from direct subprocess launches. The fifth came from the
  hidden `subprocess.check_output(["uname", "-p"])` call inside
  `platform.processor()` after an earlier test had initialized a server
  thread.
- Added `viper._subprocess.Popen` and `viper._subprocess.run`. On macOS, the
  facade starts an absolute Python bridge through `posix_spawn`; the bridge
  applies the working directory and session settings before `execve()`
  replaces it with the requested target.
- Routed every direct subprocess import beneath `src/viper` and `tests`
  through the facade, except the regression module that replaces `_fork_exec`
  with a rejecting stub.
- Removed `platform.processor()` from macOS runtime observation.
  `CPUContext.model` records the already observed architecture on macOS and
  retains the prior processor probe on other platforms.
- Registered the contract in the documentation contract set and repaired the
  generated-project file-count assertion that prevented its process result
  from being checked.
- Installed and locked the CodeQL query-pack dependencies required by the
  System Impact gate.

The final `ContractTraceabilityGraph` contains 2 requirements, 2 verifier
rules, 4 traceability edges, 60 exact targets, and 2 PairBlocks. CodeQL observed
4,796 baseline declarations and 4,835 candidate declarations with 8,280
candidate dependency edges under one `CodeQLIdentity`. The final precommit
`PlanCheck` passed all 60 targets, reported no unexpected declaration changes
or unsatisfied dependencies, and returned zero from both PairBlock gates. The
checked plan digest is
`c66eb8d9e6018da01c9f312dbfccfb42be8995949c077b335aef835f00aebdc9`.
The exact combined gate passed 160 tests with 1 skip and 2 subtests and created
no new macOS crash report. The documentation and Contract Traceability gate
passed 82 tests.

System Impact accepted implementation commit
`19691b101470f532408a17e783be9fd4007261de`. The acceptance receipt binds that
commit to passing `PlanCheck`
`432355b3c7006a148f6dd63eb0f16e89ef2fe1d4c597b0144e38c6b387b7eff8`.

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
