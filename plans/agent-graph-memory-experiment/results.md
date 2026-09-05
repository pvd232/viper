# Verified Three-Arm Result

## Verdict

This pilot does not show a graph advantage. All three arms failed hidden
acceptance.

The ordinary arm finished voluntarily in 401.8 seconds. The static-graph and
graph-predicate arms reached the externally enforced 480-second limit. All
three repaired the 50 consumer files and the governed symbol renames. Their
remaining failures were either outside the current CodeQL relationship model
or, for four stage-to-stage calls in the predicate arm, outside the predicate's
rename-only completion rule.

## Frozen comparison

| Arm | Accepted | Stop | Seconds | Commands | Recorded searches | Hidden failures |
|---|---:|---|---:|---:|---:|---:|
| Ordinary repository | no | voluntary | 401.771 | 40 | 12 | 15 |
| Static graph | no | timeout | 480.036 | 50 | 14 | 15 |
| Graph plus predicate | no | timeout | 480.039 | 34 | 8 | 19 |

Every retained result passed VIPER `verify-run`. The hidden evaluator did not
mutate any evaluated candidate. Because no arm passed, the accepted comparison
contains no efficiency winner.

The timeout arms lack token totals. Codex emits final token usage at normal turn
completion; the harness terminated those processes before that event. The
stored zero values mean “unavailable,” not zero tokens.

## What each candidate completed

The hidden evaluator found no missing consumer, stale governed name, definition,
import-count, call-count, command-file, decoy, unit-test, or runtime-consumer
failure in any arm. Each patch changed 65 tracked files.

| Arm | Added lines | Deleted lines | Remaining failures |
|---|---:|---:|---|
| Ordinary repository | 128 | 129 | Five contract states, five checklist rows, five manifest rows |
| Static graph | 148 | 198 | Five registry keys, five contract states, five manifest rows |
| Graph plus predicate | 128 | 129 | Four missing stage-to-stage `policy="verified"` arguments, five contract states, five checklist rows, five manifest rows |

The task requested updates to these non-code artifacts but did not state the
hidden evaluator's exact `state = "complete"` and manifest-row predicates.
That weakens any comparison based on those failures: the oracle required a
representation that the prompt did not fully declare.

## What the predicate actually did

The agent executed `python .viper/unresolved.py` five times. The experiment's
stored counter says six because its current substring counter also counts a
command that reads the script. Transcript inspection is authoritative for the
five executions.

The first successful query returned 98 unresolved baseline relationships. After
the bulk edit, the predicate returned four rows, all stage-to-stage callers:

- `normalize.py:normalize`
- `validate.py:validate`
- `publish.py:publish`
- `execute.py:execute`

Those rows were reported as `replacement_missing`. The hidden evaluator
instead found the renamed calls present and reported only their missing
`policy="verified"` arguments. The discrepancy has two causes:

1. the frozen obligation identifies each dependent declaration by its baseline
   name, but the compound refactor renames that dependent too; and
2. a rename relationship records the resolved target, not required keyword
   arguments.

The predicate therefore guided the agent back to the four correct files, but
its status and completion rule were wrong for this compound transformation. It
could not certify the task even after all 98 name transitions were repaired.

The transcript also shows two useful behavioral effects. The predicate exposed
a mistaken module-alias rewrite and later returned the four inner pipeline
links. It did not prevent the agent from spending substantial time on ordinary
search and repository-policy discovery.

## Query cost

A post-run benchmark used the retained predicate candidate and the same graph
evidence:

| Operation | First call | Repeated call | Output |
|---|---:|---:|---:|
| Lexical `rg` over source, config, docs, and tests | 0.033 s | 0.008–0.010 s | 6,969 bytes |
| Exact graph predicate | 13.364 s | 1.186 s | 2,096 bytes |

These operations answer different questions: `rg` returns matching text,
while the predicate resolves typed relationships and compares them with frozen
obligations. The measurement shows that the current predicate is viable as a
gate or occasional checkpoint, not as a shell command an agent should launch
repeatedly without coordination.

The live transcript also showed duplicate predicate launches while one analysis
was still running. A single-flight service should coalesce calls for the same
candidate digest.

## Apparatus incidents

Several pre-result launches were invalid and are excluded:

- the predicate initially selected Conda Python and could not import PyYAML;
- the first runtime repair relied on `VIRTUAL_ENV`, which the VIPER stage did
  not retain;
- the first executable query placed its cache inside the analyzed tree;
- overlay analysis could not run because the evidence bundle retained the
  baseline graph but not the baseline CodeQL database; and
- cancelling a VIPER run left its Codex process group alive.

The exact orphan process groups were terminated before the valid arm. The
experiment repository records the predicate-only amendments. Ordinary and
static runs use source commit `926464b`; the valid predicate run uses
`a2d2ec4`. The task, fixture, graph, prompt, evaluator, model, and timeout did
not change.

## Next implementation

The next useful version should not add broader graph traversal. It should make
the existing evidence executable and complete:

1. Add explicit baseline-dependent to candidate-dependent mappings so a caller
   may be renamed while its outgoing obligation remains identifiable.
2. Compile transformation-specific predicates alongside graph edges:
   `RequiredKeywordArgument`, `JsonKeyTransition`, `ContractState`,
   `ChecklistState`, and `DigestMatches`.
3. Serve `unresolved --summary` through a long-lived CLI/MCP process. Group by
   file and obligation type; fetch occurrence detail only on request.
4. Key candidate results by source digest and use a single-flight lock so
   concurrent calls share one analysis.
5. Mount graph evidence outside the editable candidate and expose it read-only.
6. Record usage incrementally and kill the complete descendant process group on
   cancellation.
7. Add a general software-execution stage and primary-result artifact to VIPER.
   The current experiment had to masquerade as a training stage with artifacts
   named `model` and `state`.
8. Make mixed Git/local artifact resolution, package-owned parameter loading,
   and subclass-parameter preservation native preflight behavior.

## Contract Gap and VIPER

Contract Gap should become the compiler for the non-code obligations that this
pilot missed.

A contract requirement or PairBlock would compile into:

- frozen source and external inputs;
- graph relationship obligations;
- transformation predicates over code, JSON, TOML, checklists, and digests;
- executable gates and their observing tests; and
- declared journal artifacts.

VIPER would own execution and evidence. Each PairBlock run would append
invocation receipts, predicate snapshots, patches, tests, and acceptance to a
machine-generated journal. `verify-run` would validate that evidence, and the
journal renderer would consume only verified records.

This removes the current split in which Contract Gap declares the work while
experiment code manually recreates its checklist, tests, report, and artifact
joins.

## Evidence

- Experiment root:
  `/Users/machina/Developer/ChatGPT/viper-agent-graph-memory-pilot-20260905-v9`
- Ordinary run: `01M1SM1MH6BTEZGNS619EX537Q`
- Static run: `01M1SMNZ9G6YZ5S33SWFJSSG26`
- Predicate run: `01M1SP4HQQ2VKZEPMPZEXRG0HK`
- Verified summary: `results/summary.json`
- Independent comparison: `compare.py` completed with three verified arms
- Predicate smoke test: 98 unresolved rows from the untouched fixture
- Predicate timing candidate:
  `/tmp/viper-predicate-benchmark.AQGMAq/candidate`

This is one replicate on a synthetic, graph-friendly refactor. It establishes
specific mechanism failures and timings, not a general model-performance
effect.

