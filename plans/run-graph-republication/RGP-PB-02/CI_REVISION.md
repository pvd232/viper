# PB-02 validation revision

The user requested Pyrefly on 2026-10-17. This revision uses it in the fast CI job and `make check`, with source, tests, tools, and setup code included. The existing test and release jobs remain required.

Historical check receipts retain the commands that actually ran. New validation results identify their exact commit and Pyrefly version. Corrections discovered by this check stay with their owning PairBlock and are carried forward through the PR stack.

The earlier retention-test tuple mismatch is a PB-01 caller correction carried by the PB-05 implementation. Its correction will be applied to the earlier review branches so each PR can be checked independently.

Validation of this revision is pending CI.
