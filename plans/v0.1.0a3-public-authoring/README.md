# Public authoring acceptance tests

This directory holds executable pytest source for the dependency-ordered
PairBlocks in the public authoring contract. The files stay outside `tests/`
until their owning block starts, because they describe the approved version-2
API rather than the current version-1 implementation.

For each PairBlock:

1. Move its planned file to the `planned_destination` recorded in
   `plan.json`.
2. Run that file and confirm the relevant tests fail for the missing contract.
3. Implement only the owning PairBlock.
4. Run the focused test, the live plan validator, and the change-aware wider
   checks.
5. Record the test output in the block's Git commit and closure evidence.

The live validator rejects skipped tests, duplicate test names, missing block
metadata, invalid Python, and a dependency order that differs from the master
checklist. This keeps the source ready without weakening the active suite with
temporary `xfail` or compatibility behavior.
