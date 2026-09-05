# Use the catalog, knowledge store, and MCP

The catalog is a derived SQLite index over verified evidence. The knowledge
store publishes typed scientific annotations. MCP exposes the same typed API to
an agent over local standard input and output.

## Build the local catalog

```bash
viper catalog-refresh experiments/example/runs/baseline/<run-id>/resolved.yaml \
  --root . \
  --trust-source https://github.com/example/project
```

The command verifies each supplied terminal run before indexing it. The derived
database lives at `.viper/catalog.sqlite3` and can be rebuilt from its sources.

## Search measurements

```bash
viper --json search-measurements \
  --root . \
  --query '{"metric_ids":["training_loss"],"limit":20}'
```

Equivalent Python code opens the same catalog:

```python
from viper.catalog import MeasurementQuery, catalog

page = catalog(root=root).measurements(
    MeasurementQuery(metric_ids=("training_loss",), limit=20)
)
```

## Publish and search knowledge

`knowledge(root=root)` opens the repository's knowledge store. Its publication
methods accept typed ontology, assignment, effect, impact, diagnostic,
assertion, vector, and retrieval-judgment records. Refresh the catalog with a
knowledge head before searching those records.

Knowledge records point to immutable run, stage, artifact, or measurement
targets. They annotate evidence; they do not replace it.

## Give an agent access

```bash
viper mcp --root . --access read
```

Use `--access execute` only when the client should be able to invoke execution
operations. The MCP server transports VIPER's typed operations; it does not
create a second evidence model.
