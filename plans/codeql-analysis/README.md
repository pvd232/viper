# CodeQL analysis migration

This directory holds the reviewed source plan before it is applied to the
package.

- `replace/` mirrors files that the migration replaces.
- `add/` mirrors files that the migration adds.
- `blocks/` holds the ordered semantic patches and their focused tests.
- `plan.toml` binds each planned file to its destination and PairBlock.

The files under `replace/` are complete files, not patches or snippets. The
contract is `docs/development/codeql-analysis.md`.
