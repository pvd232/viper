# Documentation architecture

The root README introduces VIPER through the CPU quickstart. The
[documentation home](../README.md) directs readers to a tutorial, task guide,
explanation, or reference page. The [internal index](../internal/README.md)
collects maintainer guides and release reports.

## Page responsibilities

| Page type | Reader's need | Content |
| --- | --- | --- |
| Tutorial | Run a first experiment. | Setup, runnable example, expected output, and a next change. |
| How-to | Complete a specific task. | Prerequisites, code or commands, results, and relevant failure conditions. |
| Explanation | Understand how the system works. | Operations in execution order, with inputs, outputs, and limitations. |
| Reference | Look up an interface. | Names, arguments, return values, constraints, and links to defining code. |
| Maintainer guide | Change or release VIPER. | Development procedures, validation commands, and release evidence. |

Keep exact schema fields in the installed schema registry. The protocol page
explains record relationships and links to model definitions. Keep historical
interfaces in release notes or clearly marked archived documents.

## Agent entry points

[The agent reference](../reference/agents.md) owns connection setup, discovery,
access modes, results, resources, and prompts. [llms.txt](../../llms.txt) is a
navigation index. MCP server instructions and `viper://guide` explain the live
connection; tool schemas come from the installed API. Contributor rules remain
in [AGENTS.md](../../AGENTS.md). The catalog guide owns indexing and queries.

Every documentation page must be reachable from the root README. The
navigation test follows links through the public and maintainer indexes;
an unreachable page fails the check.

## Examples

[`examples/cpu_quickstart.py`](../../examples/cpu_quickstart.py) owns the complete
introductory workflow. Public excerpts use the same imports, names, and calls.
Include complete function bodies and constructor arguments. Define values before
use, or identify the preceding example that creates them. Keep all setup required
to execute a tutorial on that page. Reference pages can explain fields in prose
and link to a complete example.

For each example, trace every name back to an import, argument, declaration,
or explicitly linked setup. Explain runtime-supplied arguments before their
first use. Show the actual computation and required writes. Test complete
workflows in a clean workspace to expose missing setup that mocked prerequisites
would conceal. Keep private imports and plan-publication machinery in
implementation documentation.

Keep documentation aligned with the implementation. Keep declarations in source and link to their tests. Git history preserves earlier designs.
Record release results against the exact commit or distribution tested.

An unused callback parameter may have a leading underscore, as in `_context`.
This follows the [unused-argument convention](https://docs.astral.sh/ruff/rules/unused-function-argument/)
and leaves the callback public. Use `context` when the function reads it.

Execute the code printed in tutorials and the README. A working source file alone
leaves omissions in its documentation undetected. Also validate constructor
arguments, identifiers, CLI commands, and required setup against the package.

The primary Python workflow is `plan() -> execution.run()`. Batch execution
passes drafts to `execution.run_many()`. Execution owns plan compilation and
publication; user examples call the execution API directly.

## Validation

From the repository root, with `.venv` active:

```bash
python -m pytest tests/test_documentation.py tests/test_public_inventory.py -q
python -m pytest tests/test_readme_workflow.py -q
```

The documentation tests check local links and anchors, navigation, Python
syntax, public imports, API operations, CLI commands, and release references.
The quickstart tests assemble the README and tutorial's Python blocks in order
and execute each program in a temporary Git repository. They check terminal
status, model output, every recorded measurement, and the saved checkpoint.
