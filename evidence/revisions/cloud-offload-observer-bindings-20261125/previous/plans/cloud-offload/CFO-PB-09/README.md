# CFO-PB-09

**Status:** planned; implementation code and executable PairBlockPlan not yet frozen.

**Depends on:** PB08

Context: JEP currently owns duplicate queue and generation-upload orchestration. Once native Viper passes acceptance, replace these callers in the JEP repository rather than writing JEP changes in a Viper-owned PairBlock.

## Owned targets

- csts_pilot/background_storage.py
- csts_pilot/full_data_prompt_uploads.py

## Contribution

Freeze a real current JEP baseline and its environment before planning actions. Keep private GCS configuration and workload-identity behavior, use native stable references and publication-only retry/recovery, and remove displaced queue/retention orchestration after caller migration. Do not add provenance schemas or provision GPUs. Complete separate Viper/JEP and combined maintained-code reports; net reduction remains unproven until measured.

## Observing checks

- tests/test_viper_storage_adapter.py

Exact proposed test symbols are declared in contracts/cloud-offload.toml. They are not implemented or executed by this document.

## Gate and stop condition

Freeze complete source actions from the actual dependency commit, run Pyrefly before focused CPU/mock tests, require semantic documentation/schema checks, and finish with non-mutating Ruff formatting and lint. Native process changes also require the relevant integration checks. Stop on failed validation or missing real proof; no guessed success boolean or placeholder receipt can authorize deletion.

