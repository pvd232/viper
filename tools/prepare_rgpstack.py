"""Carry checked type corrections into each PairBlock and retain new Git objects."""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path.cwd()
RESULTS = Path(os.environ['RUNNER_TEMP']) / 'rgp-stack-results'
RESULTS.mkdir()
BASE = '2bb68454e92ba04d16fbbb5d015224552ac6fc60'
FIXED = 'c3ecfe262b6e88a2fccdb563e9b1f22ce552c4fc'
HEADS = [
    ('03', '2151d6665880ab37e4bb5ad4793525cf599e6975'),
    ('04', 'f9817194faa83c495aef9355db93c103b77876a2'),
    ('05', '97cadc32fd7c640a48942933ef24b5e6f052bd54'),
    ('06', '293628b25f5fc313d85c8faf00772753d509c7a0'),
    ('07', 'f98b694fc938a13ea746a0c7a63fdc9f8883c6f7'),
]


def git(*args):
    """Read or materialize the checked-out source in this disposable runner."""
    return subprocess.check_output(['git', *args])


def read(revision, path):
    """Return one exact Git file, including its absence."""
    result = subprocess.run(['git', 'show', f'{revision}:{path}'], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def call(endpoint, payload=None):
    """Save repository objects while leaving branch pointers for operator review."""
    request = urllib.request.Request('https://api.github.com/repos/pvd232/viper/' + endpoint,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def typed_outputs(source):
    """Apply the checked output-container correction to existing authoring calls."""
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'stage', 'download'}]
    values = [kw.value for n in calls for kw in n.keywords if kw.arg == 'outputs' and isinstance(kw.value, ast.Dict)]
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    edits = [(offsets[n.lineno - 1] + n.col_offset, offsets[n.end_lineno - 1] + n.end_col_offset) for n in values]
    for start, end in sorted(edits, reverse=True):
        source = source[:start] + 'StageOutputs[OutputDraft](**' + source[start:end] + ')' + source[end:]
    imports = {a.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and n.module == 'viper.outputs' for a in n.names}
    missing = {'StageOutputs', 'OutputDraft'} - imports
    if missing:
        line = next(v for v in source.splitlines() if v.startswith('from viper.outputs import '))
        replacement = line + ('\n    ' + ',\n    '.join(sorted(missing)) + ',' if '(' in line else ', ' + ', '.join(sorted(missing)))
        source = source.replace(line, replacement, 1)
    return source


paths = git('diff', '--name-only', BASE, FIXED).decode().splitlines()
previous = FIXED
notes = {}
records = []
for index, (block, head) in enumerate(HEADS):
    git('checkout', '--force', '--detach', head)
    touched = []
    for path in paths:
        original, corrected, current = read(BASE, path), read(FIXED, path), read(head, path)
        if current == corrected:
            continue
        if current == original:
            if corrected is None:
                (ROOT / path).unlink()
            else:
                (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
                (ROOT / path).write_bytes(corrected)
        elif path == 'tests/test_run_execution.py':
            (ROOT / path).write_text(typed_outputs(current.decode()))
        else:
            raise ValueError(f'Inspect overlapping changes: PB-{block} {path}')
        touched.append(path)
    path = 'tests/fixtures.py'
    source = (ROOT / path).read_text()
    old = '        self.head = "0" * 40'
    if source.count(old) != 1:
        raise ValueError('MemoryHub head declaration changed')
    (ROOT / path).write_text(source.replace(old, '        self.head: str = "0" * 40'))
    touched.append(path)
    note_path = f'plans/run-graph-republication/RGP-PB-{block}/CI_REVISION.md'
    notes[note_path] = f'# PB-{block} validation revision\n\nThis revision includes the checked Pyrefly configuration and type corrections from PB-02. '
    notes[note_path] += 'PB-03 also gives MemoryHub.head its explicit string type; all later blocks retain that test-helper correction. '
    notes[note_path] += 'The original PairBlock implementation remains in its own PR. Historical receipts retain their actual commands. The current CI run checks the exact revised tree.\n'
    for path, text in notes.items():
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / path).write_text(text)
    if index == 0:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-e', '.[test,release,mcp,gcs]'], check=True)
    python_paths = [p for p in touched if p.endswith('.py')]
    subprocess.run(['ruff', 'check', '--select', 'I', '--fix', *python_paths], check=True)
    subprocess.run(['ruff', 'format', *python_paths], check=True)
    commands = [
        ['ruff', 'check', 'setup.py', 'src/viper', 'tests'],
        ['ruff', 'format', '--check', 'setup.py', 'src/viper', 'tests'],
        ['pyrefly', 'check', '--python-interpreter-path', sys.executable],
        [sys.executable, '-m', 'pytest', 'tests', '-q', '-m', 'unit or contract'],
    ]
    for number, command in enumerate(commands):
        result = subprocess.run(command, capture_output=True, text=True)
        (RESULTS / f'pb{block}-{number}.log').write_text(result.stdout + result.stderr)
        print('CHECK', block, command[0], result.returncode, result.stdout[-2000:], result.stderr[-2000:], flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
    changed = set(git('diff', '--name-only', head).decode().splitlines()) | set(notes)
    entries = [{'path': p, 'mode': '100644', 'type': 'blob', 'content': (ROOT / p).read_text()} for p in sorted(changed)]
    tree = call('git/trees', {'base_tree': call('git/commits/' + head)['tree']['sha'], 'tree': entries})['sha']
    parent = os.environ['SOURCE_SHA'] if block == '03' else head
    commit = call('git/commits', {'message': f'RGP-PB-{block} revision: carry verified Pyrefly checks through the stack', 'tree': tree, 'parents': [parent, previous]})['sha']
    record = {'pair_block': block, 'previous_head': parent, 'previous_base': previous, 'tree_sha': tree, 'commit_sha': commit, 'source_sha': head, 'pyrefly': subprocess.check_output(['pyrefly', '--version'], text=True).strip(), 'changed_files': sorted(changed)}
    records.append(record)
    (RESULTS / 'revisions.json').write_text(json.dumps(records, indent=2))
    print('CHECKED_REVISION', json.dumps(record), flush=True)
    previous = commit
