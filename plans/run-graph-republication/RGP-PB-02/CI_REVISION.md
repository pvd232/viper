# PB-02 validation revision

The user requested Pyrefly on 2026-10-17. The fast CI job and `make check` use it for source, tests, tools, and setup code. Integration, supported-Python, minimum-Pydantic, release, and installed-wheel checks remain enabled.

Pyrefly 0.64.1 checked the corrected source with zero errors in Actions run 39049634830. The unit and contract suite passed in the same isolated checkout. The checked source commit is `b3546bd8217f93391c59c1e240e73c48f540d083`; the retained `checked-type-revision` artifact records every modified file hash. The ordinary PR workflow checks the final committed tree again.

The fixes add accurate collection annotations, explicitly construct output collections in authoring examples, and narrow optional values. Frozen-object rejection tests still attempt assignment through `setattr`. The metric dependency test explicitly marks its partial test objects. Existing Pydantic field-override annotations remain unchanged.

The retention test now unpacks the publisher's `(snapshot, files)` result. This is a PB-01 caller correction already carried by PB-05, included here so earlier PRs validate independently.

Historical check receipts retain their executed commands. Temporary preparation files are absent from the completed source tree. Each later PR receives this shared revision while retaining its own PairBlock implementation and review history.
