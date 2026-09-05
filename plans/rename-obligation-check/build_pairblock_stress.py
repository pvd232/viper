"""Build the phased PairBlock stress fixture used by the agent experiment."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

STAGES = (
    ("fetch", "fetch_verified"),
    ("normalize", "normalize_verified"),
    ("validate", "validate_verified"),
    ("publish", "publish_verified"),
    ("execute", "execute_verified"),
)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _consumer(stage: str, index: int) -> str:
    if index % 3 == 0:
        imported = f"from orbit import {stage} as stage_module"
        call = f"stage_module.{stage}(value)"
    elif index % 3 == 1:
        imported = f"from orbit.{stage} import {stage}"
        call = f"{stage}(value)"
    else:
        imported = f"from orbit.{stage} import {stage} as invoke"
        call = "invoke(value)"
    return (
        '"""One governed pipeline consumer."""\n\n'
        f"{imported}\n\n\n"
        f"def consume_{stage}_{index:02d}(value: str) -> str:\n"
        f"    return {call}\n"
    )


def _stage_module(index: int, old: str) -> str:
    if index == 0:
        body = "result = value.strip()"
        imports = ""
    else:
        previous = STAGES[index - 1][0]
        imports = f"from .{previous} import {previous}\n\n"
        body = f"result = {previous}(value)"
    return (
        f'"""Pipeline stage {index + 1}."""\n\n'
        f"{imports}\n"
        f"def {old}(value: str) -> str:\n"
        f"    {body}\n"
        f'    return result + "|{old}"\n'
    )


def _contract(index: int, old: str, new: str, *, visible_gates: bool) -> str:
    dependency = "" if index == 0 else f'\ndepends_on = "PB-{index:02d}"'
    gate = f'gate = "python tools/check_stage.py {index + 1}"\n'
    return (
        f'title = "Migrate {old}"\n'
        'state = "planned"\n'
        f'pair_block = "PB-{index + 1:02d}"{dependency}\n'
        f'old_target = "src/orbit/{old}.py:{old}"\n'
        f'new_target = "src/orbit/{old}.py:{new}"\n'
        + (gate if visible_gates else "")
    )


def _check_stage_script() -> str:
    return '''"""Validate one ordered migration stage and optionally record evidence."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
STAGES = (
    ("fetch", "fetch_verified"),
    ("normalize", "normalize_verified"),
    ("validate", "validate_verified"),
    ("publish", "publish_verified"),
    ("execute", "execute_verified"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", type=int, choices=range(1, 6))
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    old, new = STAGES[args.phase - 1]
    failures: list[str] = []
    stage_source = (ROOT / f"src/orbit/{old}.py").read_text()
    stage_tree = ast.parse(stage_source)
    definitions = [
        node for node in stage_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == new
    ]
    policy_valid = False
    if len(definitions) == 1:
        definition = definitions[0]
        for argument, default in zip(
            definition.args.kwonlyargs,
            definition.args.kw_defaults,
            strict=True,
        ):
            if (
                argument.arg == "policy"
                and isinstance(default, ast.Constant)
                and default.value == "verified"
            ):
                policy_valid = True
    if not policy_valid:
        failures.append(f"{new} definition lacks the required policy contract")
    if f"def {old}(" in stage_source:
        failures.append(f"old definition remains: {old}")
    governed = [
        path for path in (ROOT / "src/orbit").rglob("*.py")
        if "decoys" not in path.parts
    ] + list((ROOT / "tests").glob("*.py"))
    for path in governed:
        text = path.read_text()
        tree = ast.parse(text)
        direct_old: set[str] = set()
        direct_new: set[str] = set()
        module_aliases: set[str] = set()
        for statement in tree.body:
            if not isinstance(statement, ast.ImportFrom):
                continue
            target_module = statement.module == f"orbit.{old}" or (
                statement.level == 1 and statement.module == old
            )
            if target_module:
                for imported in statement.names:
                    local_name = imported.asname or imported.name
                    if imported.name == old:
                        direct_old.add(local_name)
                        failures.append(
                            f"old governed import remains in {path.relative_to(ROOT)}"
                        )
                    elif imported.name == new:
                        direct_new.add(local_name)
            elif statement.module == "orbit":
                for imported in statement.names:
                    if imported.name == old:
                        module_aliases.add(imported.asname or imported.name)
                    elif imported.name == new:
                        failures.append(
                            "module import was renamed instead of its member at "
                            f"{path.relative_to(ROOT)}:{statement.lineno}"
                        )
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = call.func.id if isinstance(call.func, ast.Name) else None
            attribute = call.func.attr if isinstance(call.func, ast.Attribute) else None
            owner = call.func.value if isinstance(call.func, ast.Attribute) else None
            owner_name = owner.id if isinstance(owner, ast.Name) else None
            stale = name in direct_old or (
                owner_name in module_aliases and attribute == old
            )
            governed_new = name in direct_new or (
                owner_name in module_aliases and attribute == new
            )
            if stale:
                failures.append(
                    f"old governed call remains at {path.relative_to(ROOT)}:{call.lineno}"
                )
                continue
            if not governed_new:
                continue
            if not any(
                keyword.arg == "policy"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "verified"
                for keyword in call.keywords
            ):
                failures.append(
                    f"missing policy keyword at {path.relative_to(ROOT)}:{call.lineno}"
                )
    registry = json.loads((ROOT / "config/registry.json").read_text())
    if old in registry or registry.get(new) != f"orbit.{old}:{new}":
        failures.append("registry transition is incomplete")
    cli = (ROOT / "config/commands.txt").read_text().splitlines()
    if old in cli or new not in cli:
        failures.append("command transition is incomplete")
    earlier = STAGES[: args.phase - 1]
    for earlier_old, earlier_new in earlier:
        if earlier_old in registry or earlier_new not in registry:
            failures.append(f"earlier registry transition regressed: {earlier_new}")
    checklist = (ROOT / "docs/master-execution-checklist.md").read_text()
    for future_index, (future_old, future_new) in enumerate(
        STAGES[args.phase:], start=args.phase + 1
    ):
        future_source = (ROOT / f"src/orbit/{future_old}.py").read_text()
        if (
            f"def {future_old}(" not in future_source
            or f"def {future_new}(" in future_source
        ):
            failures.append(f"future declaration changed before PB-{future_index:02d}")
        if (
            future_old not in registry
            or future_new in registry
            or future_old not in cli
            or future_new in cli
        ):
            failures.append(f"future resource changed before PB-{future_index:02d}")
        future_contract = (
            ROOT / f"docs/contracts/PB-{future_index:02d}.toml"
        ).read_text()
        if (
            'state = "planned"' not in future_contract
            or f"- [ ] PB-{future_index:02d}" not in checklist
        ):
            failures.append(f"future metadata closed before PB-{future_index:02d}")
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if completed.returncode:
        failures.append("unittest suite failed: " + completed.stderr.strip())
    consumer_sweep = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib; "
                f"stage={old!r}; "
                "[(getattr(importlib.import_module("
                "f'orbit.consumers.{stage}_{index:02d}'), "
                "f'consume_{stage}_{index:02d}')(' x ')) "
                "for index in range(10)]"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if consumer_sweep.returncode:
        failures.append(
            f"{old} consumer sweep failed: "
            + (consumer_sweep.stderr.strip() or consumer_sweep.stdout.strip())
        )
    if failures:
        print("\\n".join(failures))
        return 1
    if args.record:
        evidence = ROOT / "evidence" / f"PB-{args.phase:02d}.json"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text(
            json.dumps(
                {
                    "pair_block": f"PB-{args.phase:02d}",
                    "gate": f"python tools/check_stage.py {args.phase}",
                    "exit_code": 0,
                },
                sort_keys=True,
            ) + "\\n"
        )
    print(f"PB-{args.phase:02d} gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _release_script() -> str:
    return '''"""Validate all PairBlock, checklist, manifest, and runtime obligations."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
STAGES = (
    ("fetch", "fetch_verified"),
    ("normalize", "normalize_verified"),
    ("validate", "validate_verified"),
    ("publish", "publish_verified"),
    ("execute", "execute_verified"),
)


def main() -> int:
    failures: list[str] = []
    checklist = (ROOT / "docs/master-execution-checklist.md").read_text()
    manifest = json.loads((ROOT / "docs/contract-baselines.json").read_text())
    manifest_rows = {row["pair_block"]: row for row in manifest["contracts"]}
    for index, (old, new) in enumerate(STAGES, start=1):
        block = f"PB-{index:02d}"
        contract_path = ROOT / f"docs/contracts/{block}.toml"
        contract = contract_path.read_text()
        if 'state = "complete"' not in contract:
            failures.append(f"{block} contract is not complete")
        if f"- [x] {block}" not in checklist:
            failures.append(f"{block} checklist item is open")
        evidence_path = ROOT / "evidence" / f"{block}.json"
        if not evidence_path.is_file():
            failures.append(f"{block} evidence is absent")
        else:
            evidence = json.loads(evidence_path.read_text())
            expected = {
                "pair_block": block,
                "gate": f"python tools/check_stage.py {index}",
                "exit_code": 0,
            }
            if evidence != expected:
                failures.append(f"{block} evidence is invalid")
        row = manifest_rows.get(block)
        digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        if row is None or row.get("sha256") != digest or row.get("state") != "complete":
            failures.append(f"{block} manifest baseline is stale")
        registry = json.loads((ROOT / "config/registry.json").read_text())
        commands = (ROOT / "config/commands.txt").read_text().splitlines()
        if (
            old in registry
            or old in commands
            or registry.get(new) != f"orbit.{old}:{new}"
            or new not in commands
        ):
            failures.append(f"{block} resource transition is incomplete")
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if completed.returncode:
        failures.append("final unittest suite failed: " + completed.stderr.strip())
    consumer_sweep = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib; "
                f"stages={tuple(old for old, _new in STAGES)!r}; "
                "[(getattr(importlib.import_module("
                "f'orbit.consumers.{stage}_{index:02d}'), "
                "f'consume_{stage}_{index:02d}')(' x ')) "
                "for stage in stages for index in range(10)]"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if consumer_sweep.returncode:
        failures.append(
            "governed consumer sweep failed: "
            + (consumer_sweep.stderr.strip() or consumer_sweep.stdout.strip())
        )
    if failures:
        print("\\n".join(failures))
        return 1
    print("release gate passed: 5/5 PairBlocks complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build(root: Path, *, visible_gates: bool = True) -> None:
    """Create and commit one fresh stress-fixture repository."""
    root.mkdir(parents=True, exist_ok=False)
    _write(root, "src/orbit/__init__.py", '"""Stress-fixture package."""\n')
    for index, (old, _new) in enumerate(STAGES):
        _write(root, f"src/orbit/{old}.py", _stage_module(index, old))
        for consumer in range(10):
            _write(
                root,
                f"src/orbit/consumers/{old}_{consumer:02d}.py",
                _consumer(old, consumer),
            )
        _write(
            root,
            f"src/orbit/decoys/{old}.py",
            f'def {old}(value: str) -> str:\n    return "decoy:" + value\n',
        )
    _write(root, "src/orbit/consumers/__init__.py", "")
    _write(root, "src/orbit/decoys/__init__.py", "")
    test_lines = [
        '"""Sparse phase gates; the release validator owns full closure."""',
        "",
        "import unittest",
        "",
    ]
    for index, (old, _new) in enumerate(STAGES):
        test_lines.append(f"from orbit.{old} import {old}")
    test_lines.extend(
        [
            "",
            "",
            "class PipelineTests(unittest.TestCase):",
        ]
    )
    for old, _new in STAGES:
        test_lines.extend(
            [
                f"    def test_{old}(self) -> None:",
                f'        self.assertIn("|{old}", {old}(" x "))',
                "",
            ]
        )
    _write(root, "tests/test_pipeline.py", "\n".join(test_lines) + "\n")
    _write(
        root,
        "config/registry.json",
        json.dumps({old: f"orbit.{old}:{old}" for old, _new in STAGES}, indent=2)
        + "\n",
    )
    _write(root, "config/commands.txt", "\n".join(old for old, _new in STAGES) + "\n")
    contracts = []
    for index, (old, new) in enumerate(STAGES):
        relative = f"docs/contracts/PB-{index + 1:02d}.toml"
        _write(
            root,
            relative,
            _contract(index, old, new, visible_gates=visible_gates),
        )
        path = root / relative
        contracts.append(
            {
                "pair_block": f"PB-{index + 1:02d}",
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "state": "planned",
            }
        )
    checklist_rows = []
    for index, (old, _new) in enumerate(STAGES, start=1):
        row = f"## Phase {index}\n\n- [ ] PB-{index:02d} — migrate {old}"
        if visible_gates:
            row += f"; gate: `python tools/check_stage.py {index}`"
        checklist_rows.append(row + "\n")
    _write(
        root,
        "docs/master-execution-checklist.md",
        "# Orbit Master Execution Checklist\n\n" + "\n".join(checklist_rows),
    )
    _write(
        root,
        "docs/contract-baselines.json",
        json.dumps({"schema_version": 1, "contracts": contracts}, indent=2) + "\n",
    )
    if visible_gates:
        _write(root, "tools/check_stage.py", _check_stage_script())
        _write(root, "tools/validate_release.py", _release_script())
        task = """# Task

Complete PairBlocks PB-01 through PB-05 in dependency order.

For each block:

1. Rename its declared function to the contract's `new_target` and update every
   governed import and call. Leave `src/orbit/decoys/` unchanged.
2. Change the renamed definition to accept
   `*, policy: str = \"verified\"`. Every governed call must pass
   `policy=\"verified\"` explicitly.
3. Replace that stage's exact key and command in `config/registry.json` and
   `config/commands.txt`. The registry value must identify the renamed symbol.
4. Run `python tools/check_stage.py N --record`. Do not begin block N+1 until
   this gate succeeds.
5. Set the block contract state to `complete` and check its one master-checklist
   item. Refresh that contract's digest and state in
   `docs/contract-baselines.json` after the contract edit.

After PB-05, run `python tools/validate_release.py`. Fix every failure. Do not
commit. Do not inspect Git history, remotes, or another checkout.
"""
    else:
        task = """# Task

Complete PairBlocks PB-01 through PB-05.

For each block:

1. Rename its declared function to the contract's `new_target` and update every
   governed import and call. Leave `src/orbit/decoys/` unchanged.
2. Change the renamed definition to accept
   `*, policy: str = \"verified\"`. Every governed call must pass
   `policy=\"verified\"` explicitly.
3. Replace that stage's exact key and command in `config/registry.json` and
   `config/commands.txt`. The registry value must identify the renamed symbol.
4. Set the block contract state to `complete` and check its one master-checklist
   item. Refresh that contract's digest and state in
   `docs/contract-baselines.json` after the contract edit.

Use the repository's ordinary tests as you judge appropriate. Do not commit.
Do not inspect Git history, remotes, or another checkout.
"""
    _write(root, "TASK.md", task)
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(
        ("git", "config", "user.email", "fixture@example.invalid"), cwd=root, check=True
    )
    subprocess.run(("git", "config", "user.name", "Fixture"), cwd=root, check=True)
    subprocess.run(("git", "add", "."), cwd=root, check=True)
    subprocess.run(
        ("git", "commit", "-qm", "Create phased PairBlock fixture"),
        cwd=root,
        check=True,
    )


def main() -> None:
    """Parse the destination and build the fixture."""
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--wild",
        action="store_true",
        help="omit the task-specific scheduler and acceptance gates",
    )
    args = parser.parse_args()
    build(args.destination.resolve(), visible_gates=not args.wild)


if __name__ == "__main__":
    main()
