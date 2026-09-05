"""Apply precomputed rename batches and enforce fixture PairBlock closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class ControlError(ValueError):
    """Report an invalid plan, transition batch, or scheduling operation."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ControlError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise ControlError(f"{path} does not contain a JSON object")
    return value


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _plan(root: Path, path: Path) -> tuple[tuple[dict[str, Any], ...], str]:
    document = _object(root / path)
    if document.get("schema_version") != 1:
        raise ControlError("unsupported PairBlock control-plan schema")
    transition_mode = document.get("transition_mode")
    if transition_mode not in {"manual", "worklist"}:
        raise ControlError("control plan has an invalid transition mode")
    blocks = document.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ControlError("control plan contains no PairBlocks")
    result: list[dict[str, Any]] = []
    known: set[str] = set()
    for row in blocks:
        if not isinstance(row, dict):
            raise ControlError("control-plan PairBlock is not an object")
        block_id = row.get("block_id")
        stage = row.get("stage")
        dependencies = row.get("depends_on")
        gate = row.get("gate")
        if (
            not isinstance(block_id, str)
            or not isinstance(stage, str)
            or not isinstance(dependencies, list)
            or not all(isinstance(item, str) for item in dependencies)
            or not isinstance(gate, list)
            or not gate
            or not all(isinstance(item, str) for item in gate)
        ):
            raise ControlError(f"control-plan fields are invalid for {block_id!r}")
        if block_id in known:
            raise ControlError(f"duplicate PairBlock: {block_id}")
        unknown = set(dependencies) - known
        if unknown:
            raise ControlError(
                f"{block_id} names unordered dependencies: {sorted(unknown)}"
            )
        known.add(block_id)
        result.append(row)
    return tuple(result), transition_mode


def _completed(root: Path, blocks: tuple[dict[str, Any], ...]) -> frozenset[str]:
    checklist = (root / "docs/master-execution-checklist.md").read_text(
        encoding="utf-8"
    )
    manifest = _object(root / "docs/contract-baselines.json")
    rows = manifest.get("contracts")
    if not isinstance(rows, list):
        raise ControlError("contract baseline manifest has no contracts")
    by_id = {
        row.get("pair_block"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("pair_block"), str)
    }
    complete: set[str] = set()
    for block in blocks:
        block_id = block["block_id"]
        contract_path = root / f"docs/contracts/{block_id}.toml"
        contract = contract_path.read_text(encoding="utf-8")
        row = by_id.get(block_id)
        evidence = root / "evidence" / f"{block_id}.json"
        digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        if (
            'state = "complete"' in contract
            and f"- [x] {block_id}" in checklist
            and evidence.is_file()
            and isinstance(row, dict)
            and row.get("state") == "complete"
            and row.get("sha256") == digest
        ):
            complete.add(block_id)
    return frozenset(complete)


def _ready(
    blocks: tuple[dict[str, Any], ...], completed: frozenset[str]
) -> tuple[dict[str, Any], ...]:
    return tuple(
        block
        for block in blocks
        if block["block_id"] not in completed
        and set(block["depends_on"]) <= completed
    )


def _state_path(root: Path) -> Path:
    return root / ".impact-state/applied.json"


def _state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {"schema_version": 1, "active": None, "applied": []}
    document = _object(path)
    active = document.get("active")
    values = document.get("applied")
    if (
        document.get("schema_version") != 1
        or active is not None
        and not isinstance(active, str)
        or not isinstance(values, list)
        or not all(isinstance(item, str) for item in values)
    ):
        raise ControlError("applied-state document is invalid")
    return document


def _write_state(root: Path, state: dict[str, Any]) -> None:
    _atomic_text(_state_path(root), json.dumps(state, indent=2) + "\n")


def _applied(root: Path) -> frozenset[str]:
    return frozenset(_state(root)["applied"])


def _record_applied(root: Path, block_id: str) -> None:
    state = _state(root)
    state["applied"] = sorted(set(state["applied"]) | {block_id})
    _write_state(root, state)


def _begin(root: Path, block_id: str) -> None:
    state = _state(root)
    active = state["active"]
    if active is not None and active != block_id:
        raise ControlError(f"cannot begin {block_id}; {active} is active")
    state["active"] = block_id
    _write_state(root, state)


def _worklist(root: Path, block: dict[str, Any]) -> dict[str, Any]:
    path = root / ".impact-index" / block["stage"] / "rename-worklist.json"
    document = _object(path)
    if (
        document.get("schema_version") != 2
        or document.get("coordinate_system")
        != "line_one_based_column_utf8_zero_based"
    ):
        raise ControlError(f"unsupported worklist: {path}")
    obligations_file = document.get("obligations_file")
    expected_digest = document.get("obligations_sha256")
    if not isinstance(obligations_file, str) or not isinstance(expected_digest, str):
        raise ControlError(f"worklist provenance is incomplete: {path}")
    obligations = path.parent / obligations_file
    actual_digest = hashlib.sha256(obligations.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise ControlError(f"worklist obligations digest differs: {path}")
    return document


def _apply(root: Path, block: dict[str, Any]) -> tuple[int, int]:
    document = _worklist(root, block)
    batches = document.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ControlError("worklist contains no edit batches")
    replacements: dict[Path, bytes] = {}
    edit_count = 0
    for batch in batches:
        if not isinstance(batch, dict):
            raise ControlError("worklist batch is not an object")
        relative = batch.get("path")
        edits = batch.get("edits")
        if not isinstance(relative, str) or not isinstance(edits, list) or not edits:
            raise ControlError("worklist batch fields are invalid")
        path = root / relative
        lines = path.read_bytes().splitlines(keepends=True)
        by_line: dict[int, list[dict[str, Any]]] = {}
        for edit in edits:
            if not isinstance(edit, dict):
                raise ControlError("worklist edit is not an object")
            line = edit.get("line")
            if not isinstance(line, int) or not 1 <= line <= len(lines):
                raise ControlError(f"worklist line is invalid for {relative}")
            by_line.setdefault(line, []).append(edit)
        for line_number, line_edits in by_line.items():
            source = lines[line_number - 1]
            for edit in sorted(
                line_edits, key=lambda item: item.get("column", -1), reverse=True
            ):
                column = edit.get("column")
                end_column = edit.get("end_column")
                old_text = edit.get("old_text")
                new_text = edit.get("new_text")
                if (
                    not isinstance(column, int)
                    or not isinstance(end_column, int)
                    or not isinstance(old_text, str)
                    or not isinstance(new_text, str)
                    or not 0 <= column <= end_column <= len(source)
                ):
                    raise ControlError(
                        f"worklist edit fields are invalid for {relative}"
                    )
                old_bytes = old_text.encode()
                if source[column:end_column] != old_bytes:
                    raise ControlError(
                        f"stale edit at {relative}:{line_number}:{column}; "
                        f"expected {old_text!r}"
                    )
                source = source[:column] + new_text.encode() + source[end_column:]
                edit_count += 1
            lines[line_number - 1] = source
        replacements[path] = b"".join(lines)
    for path, payload in replacements.items():
        path.write_bytes(payload)
    _record_applied(root, block["block_id"])
    return len(replacements), edit_count


def _close(root: Path, block: dict[str, Any], *, require_apply: bool) -> None:
    block_id = block["block_id"]
    state = _state(root)
    if state["active"] != block_id:
        raise ControlError(f"{block_id} is not the active PairBlock")
    if require_apply and block_id not in _applied(root):
        raise ControlError(f"{block_id} transitions have not been applied")
    completed = subprocess.run(block["gate"], cwd=root, check=False)
    if completed.returncode:
        raise ControlError(f"{block_id} gate failed with exit {completed.returncode}")
    contract_path = root / f"docs/contracts/{block_id}.toml"
    contract = contract_path.read_text(encoding="utf-8")
    marker = 'state = "planned"'
    if contract.count(marker) != 1:
        raise ControlError(f"{block_id} contract state cannot be closed")
    _atomic_text(contract_path, contract.replace(marker, 'state = "complete"'))
    checklist_path = root / "docs/master-execution-checklist.md"
    checklist = checklist_path.read_text(encoding="utf-8")
    unchecked = f"- [ ] {block_id}"
    if checklist.count(unchecked) != 1:
        raise ControlError(f"{block_id} checklist item cannot be closed")
    _atomic_text(checklist_path, checklist.replace(unchecked, f"- [x] {block_id}"))
    manifest_path = root / "docs/contract-baselines.json"
    manifest = _object(manifest_path)
    rows = manifest.get("contracts")
    if not isinstance(rows, list):
        raise ControlError("contract baseline manifest has no contracts")
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("pair_block") == block_id
    ]
    if len(matches) != 1:
        raise ControlError(f"{block_id} manifest row is not unique")
    matches[0]["state"] = "complete"
    matches[0]["sha256"] = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    _atomic_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    state = _state(root)
    state["active"] = None
    _write_state(root, state)


def _select_ready(
    blocks: tuple[dict[str, Any], ...], completed: frozenset[str], block_id: str
) -> dict[str, Any]:
    ready = _ready(blocks, completed)
    matches = [block for block in ready if block["block_id"] == block_id]
    if len(matches) != 1:
        ready_ids = [block["block_id"] for block in ready]
        raise ControlError(f"{block_id} is not ready; ready PairBlocks: {ready_ids}")
    return matches[0]


def _print_status(
    root: Path, blocks: tuple[dict[str, Any], ...], completed: frozenset[str]
) -> None:
    ready = _ready(blocks, completed)
    active = _state(root)["active"]
    print(f"Completed: {len(completed)}/{len(blocks)}")
    print(f"Active: {active or 'none'}")
    print("Ready: " + (", ".join(block["block_id"] for block in ready) or "none"))
    for block in blocks:
        block_id = block["block_id"]
        if block_id in completed:
            state = "complete"
        elif block in ready:
            state = "ready"
        else:
            waiting = sorted(set(block["depends_on"]) - completed)
            state = "blocked by " + ", ".join(waiting)
        print(f"{block_id} ({block['stage']}): {state}")


def main(argv: list[str] | None = None) -> int:
    """Apply or close only the dependency-ready PairBlock."""
    parser = argparse.ArgumentParser(prog="pairblock-control")
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="candidate repository root"
    )
    parser.add_argument(
        "--plan", type=Path, default=Path(".impact-index/pairblocks.json")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    begin_parser = commands.add_parser("begin")
    begin_parser.add_argument("block_id")
    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("block_id")
    close_parser = commands.add_parser("close")
    close_parser.add_argument("block_id")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    try:
        blocks, transition_mode = _plan(root, arguments.plan)
        completed = _completed(root, blocks)
        if arguments.command == "status":
            _print_status(root, blocks, completed)
        elif arguments.command == "begin":
            block = _select_ready(blocks, completed, arguments.block_id)
            _begin(root, block["block_id"])
            print(f"Began {block['block_id']} ({block['stage']})")
        elif arguments.command == "apply":
            if transition_mode != "worklist":
                raise ControlError("this control plan requires manual transitions")
            block = _select_ready(blocks, completed, arguments.block_id)
            if _state(root)["active"] != block["block_id"]:
                raise ControlError(f"begin {block['block_id']} before applying it")
            files, edits = _apply(root, block)
            print(f"Applied {block['block_id']}: {edits} edits in {files} files")
            print("Complete policy and resource obligations, then run close.")
        else:
            block = _select_ready(blocks, completed, arguments.block_id)
            _close(root, block, require_apply=transition_mode == "worklist")
            print(f"Closed {block['block_id']}")
            _print_status(root, blocks, _completed(root, blocks))
    except (ControlError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
