# CLI reference

The installed `viper` command maps each subcommand to one typed operation.

## Output mode

Human-readable output is the default. Put `--json` before the subcommand to receive one
typed success or failure document:

```bash
viper --json verify-run path/to/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/workspace
```

## Command groups

| Goal | Commands |
| --- | --- |
| Create and inspect a workspace | `init`, `capabilities`, `schema` |
| Validate or execute plans | `validate-stage`, `validate-resolved-stage`, `validate-run`, `freeze-run`, `preflight`, `execute-stage`, `run`, `run-many`, `retry` |
| Verify evidence | `verify-run`, `verify-benchmark`, `verify-pointer`, `execute-benchmark` |
| Inspect and recover runs | `status`, `plan-diff`, `compare-runs`, `lineage`, `restore` |
| Build and query the catalog | `catalog-refresh`, `search-runs`, `search-artifacts`, `search-measurements`, `search-benchmarks` |
| Publish and query knowledge | `knowledge refresh`, `knowledge publish`, `knowledge search` |
| Serve agent clients | `mcp` |

## Discover exact arguments

```bash
viper --help
viper run --help
viper knowledge search --help
```

The parser in [`viper.cli`](../../src/viper/cli.py) is authoritative for command names,
positional arguments, defaults, and option placement.

## Source trust

`verify-run`, `verify-benchmark`, `verify-pointer`, `lineage`, `compare-runs`, and
`catalog-refresh` require `--trust-source`. Pass the source repository URL recorded by
the run; repeat the option when more than one repository supplies code. Verification can
load executable workspace code, including artifact loaders. Select repositories whose
code you have reviewed.

## Knowledge commands

Knowledge operations use nested commands:

```bash
viper knowledge refresh --root .
viper --json knowledge search search_assertions --root . --query '{"limit":20}'
viper knowledge publish --help
```

The final argument to `knowledge search` selects the typed API operation. For example,
use `knowledge search search_assertions` to select the `search_assertions` operation.
See [catalog and knowledge](../how-to/catalog-knowledge-mcp.md) for indexing and
publication.

## Exit status

Typed command failures return exit status 1. A preflight result with failed checks also
returns 1. Successful dispatch returns 0, including a completed batch whose individual
runs failed; inspect the batch result for those outcomes.

Human-readable failures go to standard error. In JSON mode, the result or failure
document goes to standard output. The `mcp` command starts a stdio protocol server and
returns the server's exit status.
