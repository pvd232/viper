# What VIPER guarantees

VIPER checks whether a run's saved records agree with its plan and whether the
referenced files match their recorded identities. A successful verification means those
checks passed. Scientific conclusions still depend on the data, metrics, and
experimental design you selected.

## Checks on a successful run

The [run verifier](../../src/viper/verification.py) follows the terminal result
to its plan, successful attempt, stages, artifacts, and measurements. It checks that:

- the attempt belongs to the selected run and follows the allowed state changes;
- required stages have completion records and the declared outputs;
- source, config, inputs, and runtime records agree with the plan;
- retrieved files match their recorded byte counts and SHA-256 digests;
- measurements name metrics declared by the stage;
- metrics configured for recomputation agree with the saved values under their
  declared comparators.

The plan checks are implemented in the [plan
verifier](../../src/viper/_verification/plan.py); attempt and invocation checks are
implemented in the [attempt verifier](../../src/viper/_verification/attempt.py).

## Reproducibility

A plan identifies source code, input data, config, runtime requirements, and randomness
settings. The run records the observed runtime and produced files. These records let you
compare executions and investigate differences.

Deterministic settings apply to the supported runtime controls. Results can still differ
across devices, library versions, and operations. A recorded scalar is the value
supplied by the selected implementation; only metrics configured with file dependencies
and a comparator are recomputed.

## Trust and scientific interpretation

Verification depends on the recorded evidence and the source repositories you trust to
supply executable code and loaders. Assessing the truth of external observations, the
representativeness of a dataset, and the meaning of a metric requires separate review.

A causal interpretation of a comparison requires experimental controls and an assessment
of uncertainty beyond verification of the two runs.

## Restoring and searching

[Restore](../how-to/retry-restore-compare.md) checks file identities before writing
missing artifacts. It refuses to overwrite an existing file with different bytes.

The [catalog](../how-to/catalog-knowledge-mcp.md) indexes verified run evidence.
Knowledge records add author-supplied interpretations, such as an effect estimate or an
assertion. Their publication records identify what was written; the interpretation still
requires scientific review.

See the [protocol reference](../reference/protocol.md) for record types and [How VIPER
works](how-viper-works.md) for the execution sequence.
