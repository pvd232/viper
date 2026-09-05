# Rename-Check Agent Smoke Test

## Question

Can a coding agent use `viper impact rename-check` as an iterative completion
tool, and does the command identify a stale binding that declaration-level
change detection treats as changed?

## Fixture

The baseline repository contained three calls to `sample.tools.run`:

- a module-qualified call;
- a package-module alias call; and
- a directly imported symbol alias.

A fourth file called the unrelated Python standard-library
`subprocess.run`. The initial candidate renamed the declaration and the first
call. It changed the second caller's docstring while leaving its old call and
left the third alias unchanged.

Ordinary `impact analyze` reported both the first and second declarations as
changed and both old edges as removed. The exact rename checker still located
the old binding in the second declaration.

## Paired agent run

Two `gpt-5.6-luna` coding agents received separate copies of the same fixture.
The treatment prompt required `viper impact rename-check` before editing and
after every edit. The baseline prompt prohibited VIPER impact and graph
commands. Both agents ran concurrently. The paired run took 130 seconds from
spawn until both final responses arrived.

| Arm | Navigation | Observed progression | Independent final check |
|---|---|---|---|
| Treatment | Exact rename checker | `1/3` satisfied, then `2/3`, then `3/3` accepted | Accepted |
| Baseline | Repository text search | Found and repaired both remaining aliases | Accepted |

The treatment agent invoked the checker three times. The first result named
`src/sample/second.py:8` and `src/sample/third.py:8`. After the agent repaired
the second caller, the next result named only `third.py`. The final invocation
reported `Satisfied: 3/3 references`, `Unresolved: 0`, and
`Completion: accepted`. The standard-library call remained unchanged.

The baseline agent completed the same toy task through text search. An
independent rename-check invocation accepted its result in 30.41 seconds on a
cold per-repository cache.

## Result

This smoke test establishes interface usability: an agent invoked the command,
used its exact source locations as a work queue, and stopped on the derived
acceptance verdict. The result also demonstrates the semantic advantage over
`dependent_changed`: an irrelevant docstring edit changed the declaration
bytes while the checker still rejected its stale call.

The success estimate is tied at one success in each arm. Measuring marginal
localization or repair value requires a larger fixture where lexical search
yields competing aliases, generated references, or enough candidates to
exhaust the agent's search budget.

## Pre-edit worklist trial

A later paired `gpt-5.4-mini` trial compared ordinary repository navigation
with the baseline-only `rename-plan` command. Both arms began at the same
commit, made the same four correct edits, ran a Python smoke test, and were
instructed not to commit or push.

| Arm | Correct references | Repository-wide reference searches | Tool commands | Wall time | Output tokens |
|---|---:|---:|---:|---:|---:|
| Ordinary search | 4/4 | 4 | 29 | 103 s | 4,493 |
| Pre-edit worklist | 4/4 | 0 | 28 | 169 s | 6,827 |

The worklist returned all four typed occurrences before editing and the agent
used only those locations. It eliminated lexical reference searches but did
not improve correctness, total commands, tokens, or elapsed time on this tiny
fixture. CodeQL startup and unrelated agent procedure dominated the run. This
is interface evidence, not evidence of an end-to-end performance gain.

## Precomputed-index staged trial

A paired `gpt-5.3-codex-spark` trial used two fresh checkouts at fixture commit
`1339ce9c0835b6596003eb898cb1858025ce3264`. The task required three ordered
renames across eight files. Each stage had to pass the same three-test unittest
suite before the next stage began. Unrelated declarations and standard-library
calls used the same names as lexical decoys.

The treatment received three precomputed CodeQL worklists containing 6, 5,
and 4 governed reference sites. Offline worklist compilation took 16.53,
5.35, and 4.95 seconds. That cost was excluded from interactive wall time
because this trial tests a background repository index. The stdlib-only lookup
had a 45.4 ms median over 20 warm process invocations.

| Arm | Correct final references | Repository-wide searches | Validation runs | Wall time | Output tokens |
|---|---:|---:|---:|---:|---:|
| Ordinary search | 15/15 | 3 | 4 | 92 s | 6,843 |
| Precomputed graph worklist | 15/15 | 0 | 3 | 72 s | 5,399 |

Both agents produced the same source patch, preserved every decoy, and passed
an independent final test run. The ordinary-search arm omitted one test import
in Stage 1, failed validation, then found and repaired it. The graph arm used
all three worklists and passed every stage on its first validation. It had one
failed patch application caused by incorrect unchanged context; this did not
change the resulting source patch.

In this deliberately graph-friendly paired case, the precomputed index removed
three searches and one repair cycle, reduced measured wall time by 20 seconds
(22%), and reduced output by 1,444 tokens (21%). This is an `n=1` mechanism
test under favorable topology, not an estimate of general repository-task win
rate.

## Fixed-budget closure stress test

A second paired `gpt-5.3-codex-spark` trial raised the workload to four ordered
renames, 48 real consumer modules, 24 same-name decoy modules, 53 required
file edits, and 70 typed baseline reference transitions. The unittest suite
covered only representative paths. Both arms had a 120-second cutoff.

| Arm | State at cutoff | Files changed | Semantically complete transitions | Failed validations | Wall time |
|---|---|---:|---:|---:|---:|
| Ordinary search | All four stages complete | 53 | 70/70 | 2 | 87 s |
| Precomputed graph worklist | Stage 1 complete; Stage 2 partial | 16 | 20/70 | 0 | 120 s cutoff |

The ordinary-search agent batched edits with `perl` after discovering each
binding form. It initially missed package-module aliases in Stage 3 and a test
call in Stage 4; validation and a final audit repaired both. The graph agent
located every Stage 1 relationship immediately, but opened and patched most
files individually. The worklist therefore removed localization uncertainty
while increasing edit-operation overhead. On this workload, the current
row-oriented interface was decisively slower.

The exact checker exposed a separate compound-refactor limitation. It reported
67/70 satisfied transitions for the semantically complete ordinary-search
patch. The three apparent misses were calls whose targets changed correctly
but whose containing declarations were themselves renamed in later stages:
`prepare` to `prepare_verified`, `execute` to `execute_verified`, and `run` to
`run_verified`. The candidate graph retained each correct new edge under the
new owner name. Joining transitions by the baseline dependent symbol therefore
produces false `replacement_missing` results for sequential dependent renames.

The next treatment should group sites by file and binding form and emit one
batch edit plan per stage. The completion protocol also needs an explicit
baseline-to-candidate dependent-symbol mapping before it can judge compound
refactors. Another agent trial before those two changes would measure the same
known interface and join failures again.
