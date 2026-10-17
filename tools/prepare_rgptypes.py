"""Apply reviewed Pyrefly corrections in the isolated CI checkout."""

import ast
import json
from pathlib import Path

ROOT = Path.cwd()
changes = set()


def replace(path, old, new, count=1):
    """Require the inspected source expression before replacing it."""
    target = ROOT / path
    source = target.read_text()
    if source.count(old) != count:
        raise ValueError(f"Source changed: {path}: {old!r}")
    target.write_text(source.replace(old, new))
    changes.add(path)


replace('src/viper/authoring.py', '    TrainVariantStageConfig,\n', '    TrainVariantStageConfig,\n    VariantStageConfig,\n')
replace('src/viper/authoring.py', 'origin[StageDraftOutputRef]', 'cast("type[StageOutputs[StageDraftOutputRef]]", origin.__class_getitem__(StageDraftOutputRef))')
replace('src/viper/authoring.py', 'origin[OutputSpec]', 'cast("type[StageOutputs[OutputSpec]]", origin.__class_getitem__(OutputSpec))')
replace('src/viper/authoring.py', '        entries = tuple(inputs.items())', '        entries: list[tuple[InputName, StageInputDraft]] = list(inputs.items())')
replace('src/viper/authoring.py', '    stage_configs = []', '    stage_configs: list[VariantStageConfig] = []')
replace('src/viper/execution/_batch.py', 'from ..runs import RunSpec', 'from ..references import ResolvedRunSpecRef\nfrom ..runs import RunSpec')
replace('src/viper/execution/_batch.py', '    inputs = []', '    inputs: list[tuple[Path, RunSpec, ResolvedRunSpecRef | None]] = []')
replace('src/viper/http.py', '    config: type[HttpConfigT] = HttpConfig,', '    config: type[HttpConfig] = HttpConfig,')
replace('src/viper/mcp.py', '    operation = name\n', '    operation = cast(OperationName, name)\n')
replace('src/viper/_journal_encoder.py', '    model = AutoModel.from_pretrained(', '    if tokenizer is None:\n        raise ValueError("journal tokenizer is unavailable")\n    model = AutoModel.from_pretrained(')
replace('src/viper/_verification/plan.py', '        permitted_nodes: tuple[type[ast.AST], ...] = (', '        permitted_nodes: tuple[\n            type[ast.ClassDef] | type[ast.FunctionDef] | type[ast.AsyncFunctionDef], ...\n        ] = (')
replace('src/viper/verification.py', '        completed_ids = tuple(item.stage_id for item in source_attempt.resolved_stages)', '        resolved_stages = source_attempt.resolved_stages\n        completed_ids = tuple(item.stage_id for item in resolved_stages)')
replace('src/viper/verification.py', '                    for item in source_attempt.resolved_stages', '                    for item in resolved_stages')
replace('tests/test_authoring.py', '        draft.run_id = RUN_ID', '        setattr(draft, "run_id", RUN_ID)')
replace('tests/test_authoring.py', '        selected.reproducibility.parallelism.torch_intraop_threads = 8', '        setattr(selected.reproducibility.parallelism, "torch_intraop_threads", 8)')
replace('tests/test_runtime_boundary.py', '        context.stage_id = "other"  # pyright: ignore[reportAttributeAccessIssue]', '        setattr(context, "stage_id", "other")')
replace('tests/test_http_retrieval.py', '    values = {\n        "url":', '    values: dict[str, object] = {\n        "url":')
replace('tests/test_diagnostic_stage.py', 'metrics.MetricKind.__args__', 'get_args(metrics.MetricKind)')
path = 'tests/test_diagnostic_stage.py'
s = (ROOT / path).read_text()
line = next((v for v in s.splitlines() if v.startswith('from typing import ')), None)
if line:
    replace(path, line, line + ', get_args')
else:
    replace(path, 'from pathlib import Path', 'from pathlib import Path\nfrom typing import get_args')

# Keep the existing output values in explicitly typed collections.
for path in ('tests/test_authoring.py', 'tests/test_execution_signals.py', 'tests/test_run_execution.py'):
    source = (ROOT / path).read_text()
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'stage', 'download'}]
    expressions = [kw.value for n in calls for kw in n.keywords if kw.arg == 'outputs' and isinstance(kw.value, ast.Dict)]
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    edits = []
    for expression in expressions:
        start = offsets[expression.lineno - 1] + expression.col_offset
        end = offsets[expression.end_lineno - 1] + expression.end_col_offset
        edits.append((start, end, source[start:end]))
    updated = source
    for start, end, old in sorted(edits, reverse=True):
        updated = updated[:start] + 'StageOutputs[OutputDraft](**' + old + ')' + updated[end:]
    if updated != source:
        replace(path, source, updated)
    source = (ROOT / path).read_text()
    imported = {a.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and n.module == 'viper.outputs' for a in n.names}
    missing = {'StageOutputs', 'OutputDraft'} - imported
    if missing:
        line = next(v for v in source.splitlines() if v.startswith('from viper.outputs import '))
        if '(' in line:
            replace(path, line, line + '\n    ' + ',\n    '.join(sorted(missing)) + ',')
        else:
            replace(path, line, line + ', ' + ', '.join(sorted(missing)))
    source = (ROOT / path).read_text()
    comment = '  # pyright: ignore[reportArgumentType]'
    for old in [s for s in source.splitlines() if 'outputs=StageOutputs[OutputDraft]' in s and comment in s]:
        if old in (ROOT / path).read_text():
            replace(path, old, old.replace(comment, ''), (ROOT / path).read_text().count(old))

# These three test doubles expose the fields consumed by dependency lookup.
path = 'tests/test_metric_provenance.py'
source = (ROOT / path).read_text()
function = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == 'test_metric_dependencies_reuse_snapshot_references')
for call in [n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'SimpleNamespace']:
    old = ast.get_source_segment(source, call)
    replace(path, old, 'cast(Any, ' + old + ')')
s = (ROOT / path).read_text()
line = next((v for v in s.splitlines() if v.startswith('from typing import ')), None)
if line:
    existing = {x.strip() for x in line.split(' import ', 1)[1].split(',')}
    extra = sorted({'Any', 'cast'} - existing)
    if extra:
        replace(path, line, line + ', ' + ', '.join(extra))
else:
    replace(path, 'from types import SimpleNamespace', 'from types import SimpleNamespace\nfrom typing import Any, cast')

Path('/tmp/rgp-type-paths.json').write_text(json.dumps(sorted(changes)))
