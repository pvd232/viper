# CLI reference

The installed `viper` command maps each subcommand to one typed operation.

## Output mode

Human-readable output is the default. Put `--json` before the subcommand to
receive one typed success or failure document:

```bash
viper --json verify-run path/to/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/project
```

## Command groups

| Goal | Commands |
| --- | --- |
| Create and inspect a project | `init`, `capabilities`, `schema` |
| Validate or execute plans | `validate-stage`, `validate-resolved-stage`, `validate-run`, `freeze-run`, `preflight`, `execute-stage`, `run`, `run-many`, `retry` |
| Verify evidence | `verify-run`, `verify-benchmark`, `verify-pointer`, `execute-benchmark` |
| Inspect and recover runs | `status`, `plan-diff`, `compare-runs`, `lineage`, `restore` |
| Build and query the catalog | `catalog-refresh`, `search-runs`, `search-artifacts`, `search-measurements`, `search-benchmarks` |
| Publish and query knowledge | `knowledge refresh`, `knowledge publish`, `knowledge search` |
| Serve agent clients | `mcp` |
| Inspect source impact | `impact analyze`, `impact explain` |

## Discover exact arguments

```bash
viper --help
viper run --help
viper knowledge search --help
```

The parser in [`viper.cli`](../../src/viper/cli.py) is authoritative for command
names, positional arguments, defaults, and option placement.
