# CFO-PB-09

**Owner decision, 2026-11-25:** The user accepted the measured code-size increase and authorized the PyPI release. The net-reduction objective is waived as a release gate; the measured counts and historical verifier findings remain intact. [Approval record](../../../evidence/revisions/cloud-offload-size-override-20261125.json).

**Requirements:** CFO-REQ-10

**Depends on:** PB08

**Status:** JEP adapter migration is committed at `e2285b8`; final commit `d44073e` pins Viper `df10a3e`. The final bounded suite and Pyrefly pass; the owner exception accepts the measured size increase.

The bound checkout is /Users/machina/Developer/ChatGPT/jep-native-offload, branch codex/jep-native-offload, baseline c2f9716e398dd5442ca9d3579dfa788657a6cd00. [The retained change manifest](jep/proposal.json) records the actual touched source, tests and validation outputs. The manifest identifies final commit `d44073e296a638944a83684e9635d9b7fffc104f`, which pins Viper `df10a3e2258a28d7eb276d5a35a5621c0384a694`. The changes are in [draft JEP PR 26](https://github.com/pvd232/JEP/pull/26), against the original `c2f9716` baseline.

The adapter uses native workflows, enrollment, publication copies and verified restoration while preserving the selected private cloud namespace and attached identity configuration. A generation acknowledgment follows verified native copies. Failed publication retains control sources and leaves the acknowledgment absent; scientific computation is not rerun by the publication-only adapter.

Meaningful cases are tests/test_viper_storage_adapter.py::test_generation_ack_follows_verified_native_copies and test_failed_copy_keeps_control_sources_without_ack, with additional restore/target/auth cases. The retained [final CPU log](../../../evidence/cloud-offload-implementation-20261125/validation/jep-tests.log) reports 47 passing cases plus 4 subtests in 2.80 seconds; [final Pyrefly](../../../evidence/cloud-offload-implementation-20261125/validation/jep-pyrefly.log) reports zero errors. The earlier 44-case log is historical. All 227 selected Viper integration cases pass across bounded runs. All seven hosted Viper CI jobs passed at runtime commit `df10a3e`. Transfer boundaries are controlled and no live cloud/campaign run is established.

The change manifest and actual JEP PR retain the migration; redundant proposal diff copies are retired in [the path/hash record](jep/retired-diffs.json). Their removal receives no code-reduction credit. [The final independently counted working tree](../../../evidence/cloud-offload-implementation-20261125/review-10/README.md) measures JEP runtime 36,917 to 36,827 (-90) and tests 11,130 to 11,271 (+141), total +51 maintained lines. Viper grows as well; this measured size tradeoff is accepted by the owner. These counts supersede the earlier proposal totals. The report records JEP source freeze `e2285b8` and current head `d44073e`; final bounded validation and dependency-pin evidence are linked above. The Viper source dependency is `df10a3e`.

Source changes and ordinary test logs are distinct from formal acceptance. No lifecycle receipt is created by this document.
