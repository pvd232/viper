# VIPER repository instructions

Use this file as the repository-wide entry point. Apply the global Codex
working agreements and load the user-scoped skills relevant to the active task.

## Repository orientation

- Read `README.md`, `pyproject.toml`, and the nearest relevant documentation and
  tests before changing implementation behavior.
- Treat package code, tests, examples, user documentation, and release evidence
  as distinct artifacts. Relocate an artifact only when its documented owner
  changes.
- Keep public entities in the domain modules listed in
  `docs/reference/api.md`.
- Keep serialized protocol fields and discriminators stable during Python
  module refactors.

## Runtime environment

- Read `README.md` and `pyproject.toml` before running repository Python,
  package, test, schema, or validation commands.
- Use the project-local `.venv` created by the setup procedure in
  `CONTRIBUTING.md`.
- Activate `.venv` before running repository commands and verify that the
  Python interpreter resolves beneath that directory.
- Reactivate `.venv` at the start of every new shell. Environment activation
  is session-scoped.

## Evidence and documentation

- Use `source-grounding` for substantive technical, scientific, mathematical,
  empirical, historical, or implementation claims.
- Use `technical-white-paper` for concise technical concept papers,
  `latex-authoring` for mathematical Markdown, and `directory-readme` for a
  substantial directory README.
- Verify implementation claims against defining code, configuration, tests,
  callers, and outputs. Distinguish current implementation from proposals and
  exploratory evidence.
- Link repository files with paths relative to the document containing the
  link. Keep literal paths unlinked only in commands, code blocks, file trees,
  diagrams, and configuration examples.

## Changes and validation

- Keep edits within the requested scope and preserve unrelated working-tree
  changes.
- Change source files that own generated caches, package metadata, and compiled
  artifacts.
- Run targeted tests for changed behavior, followed by broader validation when
  the change crosses modules or protocol boundaries.
- Base every renderer, link, test, and empirical pass claim on an executed or
  inspected result. Report the exact command and result.
