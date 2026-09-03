# CodeQL impact observations

This ledger measures whether the System Impact Check adds useful dependency
information during contract execution. The governing contract remains the
[System Impact Check](system-impact-compiler.md). This document records
observations. The System Impact Check alone defines requirements and acceptance
rules.

The evaluation asks one question:

> Did `inspect_plan()` report a direct dependent outside the agent's or
> reviewer's existing inspection plan, and did that report change the accepted
> implementation or its tests?

## Observation method

For each code-changing contract:

1. Record the selected `ContractTarget.target` values and any additional
   declarations already chosen for propagation review before reading
   `Impact.affected`. This is the pre-report consideration set.
2. Run `analyze_source()` and `inspect_plan()` against the accepted baseline.
3. Compute the novel reported set as `Impact.affected` minus the pre-report
   consideration set.
4. Classify each novel declaration as requiring a source change, requiring a
   test change, requiring review only, or remaining unresolved.
5. After acceptance, record any important dependency discovered outside the
   report and the reason it was absent.

Freezing the pre-report consideration set before CodeQL participates makes
incremental value observable. A run that omits the frozen set measures report
volume and resulting action only; the report's informational contribution
remains unknown.

The measured quantities are:

| Quantity | Meaning |
| --- | --- |
| Planned targets | Exact `ContractTarget` declarations selected before implementation |
| Baseline-resolved targets | Planned declarations present in the baseline `SourceGraph` and eligible for incoming-edge analysis |
| Reported dependents | Unique declarations in `Impact.affected` |
| Novel dependents | Reported dependents absent from the pre-report consideration set |
| Actionable novel dependents | Novel dependents that cause a source, test, or explicit review change |
| Review-only dependents | Reported dependents reviewed while the accepted implementation stays unchanged |
| Missed dependencies | Relevant dependencies found later and absent from `Impact.affected` |

The current check covers policy-selected incoming edges present in the
baseline `SourceGraph`. Its claim ends at that represented scope.
The first CodeQL query pack omits write edges, external-library targets, and
relationships beyond its queries' resolution. Added declarations also lack
baseline incoming edges.

## Observations

### 2026-09-03 — Child-process launching

The [Child-process launching contract](child-process-launching.md) executed
`P2-CPL-01` and `P2-CPL-02` from baseline commit `7e338111` and accepted commit
`19691b10`.

| Observation | Result |
| --- | --- |
| Planned targets | 60: 38 additions and 22 updates |
| Baseline graph | 4,796 declarations and 8,195 dependency edges |
| Candidate graph | 4,835 declarations and 8,280 dependency edges |
| Reported dependents | 2 declarations through 4 evidence edges |
| Pre-report consideration set | Unavailable; this run predated the measurement protocol |
| Action caused by the report | Review only; accepted source and tests stayed unchanged |
| CodeQL-only defect discoveries | 0 |
| Final plan result | 60 targets passed; 0 unexpected declarations; 0 unsatisfied dependencies; both PairBlock gates passed |

The report identified two wrappers around
`src/viper/runtime.py:_observe_execution`:

- `src/viper/runtime.py:observe_local_execution`
- `src/viper/runtime.py:observe_gce_execution`

Each wrapper contributed one `calls` edge and one `reads` edge. Review found
that neither wrapper required a source or test change.

The decisive crash path was
`_observe_execution -> platform.processor -> subprocess.check_output -> fork`.
The report omitted that path. The current
[dependency query](../../tools/codeql/viper-python-impact/Dependencies.ql)
requires the target to have a repository-relative source path, which excludes
the standard-library `platform.processor` target.

This run establishes audit value: CodeQL independently bound the accepted
source to the selected plan and exposed the represented direct callers.
Incremental repair value remains unmeasured. The missing external call also
shows why the report must retain its represented-and-policy-selected scope.

The accepted plan digest was
`c66eb8d9e6018da01c9f312dbfccfb42be8995949c077b335aef835f00aebdc9`.
The acceptance check digest was
`432355b3c7006a148f6dd63eb0f16e89ef2fe1d4c597b0144e38c6b387b7eff8`.

## Review point

Review this ledger after five additional accepted code-changing contracts.
Retain one-hop reporting as a default gate when it repeatedly supplies an
actionable novel dependent or catches an omitted declaration. Keep it as
advisory audit evidence when reports remain correct and produce review-only
outcomes. Revise or narrow the query and policy when missed dependencies or
review-only volume dominate.
