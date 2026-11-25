# CFO-PB-06 recovery repair

Parent: `1b8ed60`, the native admission checkpoint.

Resolved source reads now use their recorded identity through the shared resolver,
including producer plans, artifact loaders, HTTP source/configuration and portable
export recording. Matching local Git producer roots remain a fallback before a
remote Git fetch. Origin and expected byte identities are still checked.

Import independently verifies every remote member while equal content shares a
stable cache inode. A nested workflow inherits omitted targets and rejects an
explicit empty or changed target set.

Observed checks:

- 80 verifier, HTTP and workflow cases and four subtests passed.
- The real fresh-workspace producer observer passed: execute/retry/publish, delete
  the original repository, import its receipt in an independent checkout, remove
  cached source bytes, forbid Git remote access, then verify the unchanged artifact
  reference through a cloud download. It performs no reupload.
- Two duplicate-content import cases passed, including empty logs. Both remote
  members are checked while one shared payload remains valid.
- The nested target regression passed. Reviewer 03 independently approved native
  routing, reuse and the explicit target boundary.

These checks use controlled cloud providers. Broad integration and final acceptance
are recorded separately. The maintained-code reduction condition remains unmet.
