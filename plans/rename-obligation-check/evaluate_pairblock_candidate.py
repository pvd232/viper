"""Evaluate one gate-free PairBlock stress candidate outside the agent checkout."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

STAGES = (
    ("fetch", "fetch_verified", 12, 8),
    ("normalize", "normalize_verified", 12, 8),
    ("validate", "validate_verified", 12, 8),
    ("publish", "publish_verified", 12, 8),
    ("execute", "execute_verified", 11, 7),
)


def _governed_paths(root: Path) -> tuple[Path, ...]:
    paths = [
        path
        for path in (root / "src/orbit").rglob("*.py")
        if "decoys" not in path.parts
    ]
    paths.extend((root / "tests").glob("*.py"))
    return tuple(sorted(paths))


def _source_failures(
    root: Path,
    old: str,
    new: str,
    expected_calls: int,
    expected_imports: int,
) -> list[str]:
    failures: list[str] = []
    target_path = root / f"src/orbit/{old}.py"
    target_tree = ast.parse(target_path.read_text(encoding="utf-8"))
    definitions = [
        node
        for node in target_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == new
    ]
    if len(definitions) != 1:
        failures.append(f"{new} definition is absent or repeated")
    else:
        definition = definitions[0]
        defaults = dict(
            zip(
                (argument.arg for argument in definition.args.kwonlyargs),
                definition.args.kw_defaults,
                strict=True,
            )
        )
        default = defaults.get("policy")
        if not isinstance(default, ast.Constant) or default.value != "verified":
            failures.append(f"{new} policy contract is incomplete")
    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == old
        for node in target_tree.body
    ):
        failures.append(f"old definition remains: {old}")
    governed_calls = 0
    governed_imports = 0
    for path in _governed_paths(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
                            "old import remains: "
                            f"{path.relative_to(root)}:{statement.lineno}"
                        )
                    elif imported.name == new:
                        direct_new.add(local_name)
                        governed_imports += 1
            elif statement.module == "orbit":
                for imported in statement.names:
                    if imported.name == old:
                        module_aliases.add(imported.asname or imported.name)
                    elif imported.name == new:
                        failures.append(
                            "module identity changed: "
                            f"{path.relative_to(root)}:{statement.lineno}"
                        )
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = call.func.id if isinstance(call.func, ast.Name) else None
            attribute = call.func.attr if isinstance(call.func, ast.Attribute) else None
            owner = call.func.value if isinstance(call.func, ast.Attribute) else None
            owner_name = owner.id if isinstance(owner, ast.Name) else None
            stale = name in direct_old or (
                owner_name in module_aliases and attribute == old
            )
            governed = name in direct_new or (
                owner_name in module_aliases and attribute == new
            )
            if stale:
                failures.append(
                    f"old call remains: {path.relative_to(root)}:{call.lineno}"
                )
            if not governed:
                continue
            governed_calls += 1
            if not any(
                keyword.arg == "policy"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "verified"
                for keyword in call.keywords
            ):
                failures.append(
                    f"policy argument is absent: {path.relative_to(root)}:{call.lineno}"
                )
    if governed_calls != expected_calls:
        failures.append(
            f"{new} governed-call count is {governed_calls}, expected {expected_calls}"
        )
    if governed_imports < expected_imports:
        failures.append(
            f"{new} governed-import count is {governed_imports}, "
            f"expected at least {expected_imports}"
        )
    return failures


def evaluate(root: Path) -> tuple[str, ...]:
    """Return every hidden acceptance failure for one candidate."""
    failures: list[str] = []
    for old, new, expected_calls, expected_imports in STAGES:
        failures.extend(
            _source_failures(root, old, new, expected_calls, expected_imports)
        )
    registry = json.loads((root / "config/registry.json").read_text(encoding="utf-8"))
    commands = (root / "config/commands.txt").read_text(encoding="utf-8").splitlines()
    checklist = (root / "docs/master-execution-checklist.md").read_text(
        encoding="utf-8"
    )
    manifest = json.loads(
        (root / "docs/contract-baselines.json").read_text(encoding="utf-8")
    )
    manifest_rows = {row["pair_block"]: row for row in manifest["contracts"]}
    for index, (old, new, _expected_calls, _expected_imports) in enumerate(
        STAGES, start=1
    ):
        block_id = f"PB-{index:02d}"
        if old in registry or registry.get(new) != f"orbit.{old}:{new}":
            failures.append(f"{block_id} registry transition is incomplete")
        if old in commands or new not in commands:
            failures.append(f"{block_id} command transition is incomplete")
        contract_path = root / f"docs/contracts/{block_id}.toml"
        contract = contract_path.read_text(encoding="utf-8")
        if 'state = "complete"' not in contract:
            failures.append(f"{block_id} contract is incomplete")
        if f"- [x] {block_id}" not in checklist:
            failures.append(f"{block_id} checklist item is open")
        digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        row = manifest_rows.get(block_id)
        if row is None or row.get("state") != "complete" or row.get("sha256") != digest:
            failures.append(f"{block_id} manifest row is stale")
    decoy_diff = subprocess.run(
        ("git", "diff", "--quiet", "HEAD", "--", "src/orbit/decoys"),
        cwd=root,
        check=False,
    )
    if decoy_diff.returncode:
        failures.append("one or more decoy modules changed")
    tests = subprocess.run(
        (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"),
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    if tests.returncode:
        failures.append("unittest suite failed: " + tests.stderr.strip())
    sys.path.insert(0, str(root / "src"))
    try:
        for old, _new, _expected_calls, _expected_imports in STAGES:
            for index in range(10):
                module_name = f"orbit.consumers.{old}_{index:02d}"
                try:
                    module = importlib.import_module(module_name)
                    function = getattr(module, f"consume_{old}_{index:02d}")
                    function(" x ")
                except Exception as error:  # noqa: BLE001
                    failures.append(
                        f"consumer failed: {module_name}: "
                        f"{type(error).__name__}: {error}"
                    )
    finally:
        sys.path.pop(0)
        for module_name in tuple(sys.modules):
            if module_name == "orbit" or module_name.startswith("orbit."):
                del sys.modules[module_name]
    return tuple(failures)


def main() -> int:
    """Evaluate the requested candidate and print one compact verdict."""
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    arguments = parser.parse_args()
    failures = evaluate(arguments.root.resolve())
    if failures:
        print("\n".join(failures))
        return 1
    print("hidden acceptance passed: 98 transitions; 50/50 consumers; 5/5 blocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
