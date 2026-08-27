# VIPER repository instructions

Use this file as the repository-wide entry point. Apply the global Codex
working agreements and load the user-scoped skills relevant to the active task.

## Repository orientation

- Read `README.md`, `pyproject.toml`, and the nearest relevant documentation and
  tests before changing implementation behavior.
- Treat package code, tests, examples, contracts, user documentation, and
  release evidence as distinct artifacts. Relocate an artifact only when the
  owning contract or approved execution checklist requires the move.
- Keep public entities in the owner modules defined by
  `docs/contracts/PACKAGE_RELEASE.md`.
- Keep serialized protocol fields and discriminators stable during Python
  module refactors.

## Runtime environment

- Read `README.md` and `pyproject.toml` before running repository Python,
  package, test, schema, or validation commands.
- Activate the Conda environment named `mantra` before running those commands.
- Verify the active environment and Python interpreter once per shell session.
- Reactivate `mantra` whenever a new shell session starts. Do not assume that
  activation from an earlier shell persists.

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
- Do not modify generated caches, package metadata, or compiled artifacts as a
  substitute for changing their source.
- Run targeted tests for changed behavior, followed by broader validation when
  the change crosses modules or contracts.
- Report exact commands and results. Do not claim that a renderer, link check,
  test, or empirical validation passed unless it was executed or inspected.
