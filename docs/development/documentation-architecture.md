# Documentation architecture

The root README introduces VIPER through the CPU quickstart. The
[documentation home](../README.md) directs readers to a tutorial, task guide,
explanation, or reference page. The [internal index](../internal/README.md)
collects release contracts and maintainer records.

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

## Examples

[`examples/cpu_quickstart.py`](../../examples/cpu_quickstart.py) owns the complete
introductory workflow. Public excerpts use the same imports, names, and calls.
Mark abbreviated examples and identify any values the reader must supply.
Parsing checks syntax. Also validate constructor
arguments, identifiers, CLI commands, and required setup against the package.

The primary Python workflow is `plan() -> execution.run()`. The batch guide
also explains `freeze_run_plan()` for saving plans before execution.

## Validation

From the repository root, with `.venv` active:

```bash
python -m pytest tests/test_documentation.py tests/test_public_inventory.py -q
python -m pytest tests/test_readme_workflow.py -q
```

The documentation tests check local links and anchors, navigation, Python
syntax, public imports, API operations, CLI commands, and release references.
The quickstart test executes the example in a temporary Git repository and
checks its terminal status and model output.
