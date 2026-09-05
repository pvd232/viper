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
