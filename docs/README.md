# VIPER documentation

Run your first experiment with the tutorial, or choose a guide for a specific task.

## Tutorial

[Build your first experiment](tutorials/getting-started.md) runs the CPU
example, shows what VIPER writes, and explains how to modify the experiment.

Continue with [a pipeline of stages](tutorials/stages.md) or
[inspection and catalog queries](tutorials/inspect-results.md). Both tutorials
provide complete Python programs.

## How-to guides

| Task | Guide |
| --- | --- |
| Choose and connect stage kinds | [Compose stages](how-to/stages.md) |
| Execute a saved plan and handle outcomes | [Execute a plan and read its result](how-to/execution.md) |
| Supply files or download data | [Load local and HTTP inputs](how-to/inputs.md) |
| Record measurements and acceptance criteria | [Define metrics and benchmarks](how-to/metrics-and-benchmarks.md) |
| Generate and execute several runs | [Run variants and replicates](how-to/variants-and-replicates.md) |
| Recover or inspect completed work | [Retry, restore, and compare runs](how-to/retry-restore-compare.md) |
| Search evidence or expose it to an agent | [Use the catalog, knowledge store, and MCP](how-to/catalog-knowledge-mcp.md) |
| Diagnose a failed command or run | [Troubleshoot VIPER](how-to/troubleshooting.md) |

## Explanation

- [How VIPER works](explanation/how-viper-works.md) follows the CPU
  example from its training function to the saved result.
- [What VIPER guarantees](explanation/guarantees.md) explains which checks
  VIPER performs and what a successful result means.

## Reference

The [reference index](reference/README.md) routes to the Python API, CLI,
configuration, formal protocol, and versioning policy.

## Contributing and internal engineering

- [Contributing](../CONTRIBUTING.md) covers repository setup and change delivery.
- [Testing VIPER](development/testing.md) defines the validation tiers and domains.
- [Internal engineering index](internal/README.md) is the single entry point for
  the active release contract, maintainer guides, architecture decisions, and
  release evidence. These documents govern VIPER development.

## Documentation checks

See the [workflow coverage map](development/documentation-review.md).
From the repository root, with `.venv` active:

```bash
python -m pytest tests/test_documentation.py tests/test_public_inventory.py -q
python -m pytest tests/test_readme_workflow.py -q
```
