# What VIPER guarantees

A successful run has passed VIPER's checks against its saved plan. Those checks
cover the recorded execution and the files it produced. Assessing whether the
experiment answers your research question requires scientific review.

## Checks on a successful run

VIPER follows the references in the saved result and checks that:

- the attempt belongs to the selected run and follows the allowed state changes;
- required stages have completion records and the declared outputs;
- source, config, inputs, and runtime records agree with the plan;
- retrieved files match their recorded byte counts and SHA-256 digests;
- measurements name metrics declared by the stage;
- metrics configured for recomputation agree with the saved values under their
  declared comparators.

## Reproducibility

The reproducible policy selects deterministic execution settings. The relaxed
policy permits nondeterministic algorithms. Both policies record the controls
read from the workers, and verification compares those readings with the plan.

Use [benchmark comparisons](../how-to/metrics-and-benchmarks.md) to check
whether repeated runs produced identical files. Device and library differences
can affect the results.

A recorded measurement is the value returned by its metric function. Metrics
configured with file dependencies and a comparator are also recomputed from
the saved files and checked against their recorded values.

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
