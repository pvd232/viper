# What VIPER guarantees

VIPER's guarantee is about recorded execution identity and protocol
relationships. It is not a claim that an experiment's scientific design is
correct.

## The core claim

For one accepted run, let (P) be the frozen plan, (A) the successful
attempt, (O) the observed artifacts and measurements, and (R) the terminal
result. VIPER accepts (R) only when:

\[
\operatorname{Accept}(R)
\Rightarrow
\operatorname{Matches}(A,P)
\land
\operatorname{Produced}(A,O)
\land
\operatorname{Identified}(O)
\land
\operatorname{Closes}(R,A,P,O).
\]

In plain English: the successful attempt must belong to the frozen plan; its
declared outputs must be recorded by exact identity; and the terminal result
must point back to that same attempt and plan.

## What is checked

- Frozen source, stage, parameter, input, environment, and reproducibility
  records are internally consistent.
- Referenced files match their recorded paths, byte counts, and SHA-256 digests.
- Attempt state changes follow the allowed durable transition sequence.
- Required stages and artifacts are present before terminal success.
- Recorded measurements belong to metrics authorized by their stage.
- Restore reads verified bytes before writing a destination.
- Catalog and knowledge queries derive from verified or explicitly published
  evidence records.

## What is not proved

VIPER does not prove that:

- a model is accurate outside the measurements you selected;
- a dataset is representative, lawful, unbiased, or free of label errors;
- a metric captures the scientific concept you care about;
- deterministic settings remove every source of physical nondeterminism;
- an external service was honest before its returned bytes were checked;
- two runs support a causal conclusion.

Those claims require domain review, experimental design, and evidence beyond
the execution protocol.

## Why exact identities matter

A filename alone can be reused for different bytes. A function name alone can
refer to changed source. VIPER therefore connects human-readable names to byte
counts and cryptographic digests. That lets later verification detect drift
instead of assuming that a familiar path still names the original object.

See the [formal protocol](../reference/protocol.md) for serialized models and
[How VIPER works](how-viper-works.md) for one complete execution.
