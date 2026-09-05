# VIPER documentation

Choose the kind of help you need. The tutorial teaches one complete workflow;
how-to guides solve a specific task; explanations describe why the system works;
reference pages define exact interfaces and records.

## Tutorial

[Build your first experiment](tutorials/getting-started.md) runs the checked CPU
example, shows what VIPER writes, and gives you a small project to modify.

## How-to guides

| Task | Guide |
| --- | --- |
| Supply files or download data | [Load local and HTTP inputs](how-to/inputs.md) |
| Record measurements and acceptance criteria | [Define metrics and benchmarks](how-to/metrics-and-benchmarks.md) |
| Generate and execute several runs | [Run variants and replicates](how-to/variants-and-replicates.md) |
| Recover or inspect completed work | [Retry, restore, and compare runs](how-to/retry-restore-compare.md) |
| Search evidence or expose it to an agent | [Use the catalog, knowledge store, and MCP](how-to/catalog-knowledge-mcp.md) |
| Diagnose a failed command or run | [Troubleshoot VIPER](how-to/troubleshooting.md) |

## Explanation

- [How VIPER works](explanation/how-viper-works.md) follows the checked CPU
  example from Python source to a verified terminal result.
- [What VIPER guarantees](explanation/guarantees.md) separates recorded identity,
  execution evidence, and verification from claims VIPER does not make.

## Reference

The [reference index](reference/README.md) routes to the Python API, CLI,
configuration, formal protocol, and versioning policy.

## Contributing and internal engineering

- [Contributing](../CONTRIBUTING.md) covers repository setup and change delivery.
- [Testing VIPER](development/testing.md) defines the validation tiers and domains.
- [Internal engineering index](internal/README.md) is the single entry point for
  executable contracts, the master checklist, architecture plans, and release
  evidence. These documents govern VIPER development; they are not user guides.

## Validate these docs

From the repository root, with `.venv` active:

```bash
python -m pytest tests/test_readme_workflow.py -q
python -m pytest tests/test_documentation.py -q -k documentation_navigation
```
