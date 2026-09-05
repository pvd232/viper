"""Compare completed contract targets with their current Python declarations."""

from __future__ import annotations

import ast

import viper._contract_traceability as traceability
from tests._documentation import (
    IMPLEMENTATION_CONTRACTS,
    MASTER_EXECUTION_CHECKLIST,
    ROOT,
)
from viper._contract_traceability import ContractTarget
from viper._system_impact.source import (
    declaration_payload,
    extract_declaration_bytes,
)

EXTERNAL_INPUT_ROOTS = ROOT / "docs/development/external-input-roots.md"

_COMPARABLE_DECLARATIONS = (
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Assign,
    ast.AnnAssign,
)


def _checked_block_order() -> dict[str, int]:
    """Return checked PairBlocks in master-checklist order."""
    text = MASTER_EXECUTION_CHECKLIST.read_text(encoding="utf-8")
    ordered: dict[str, int] = {}
    for checkbox in traceability._CHECKBOX.finditer(text):
        if not checkbox.group(0).startswith(("- [x]", "- [X]")):
            continue
        markers = tuple(traceability._PAIR_BLOCK_MARKER.finditer(checkbox.group(0)))
        if not markers:
            continue
        assert len(markers) == 1, checkbox.group(0).splitlines()[0]
        block_id = markers[0].group("id")
        assert block_id not in ordered, block_id
        ordered[block_id] = len(ordered)
    return ordered


def _latest_checked_targets(
    identities: set[tuple[str, str]],
) -> dict[tuple[str, str], ContractTarget]:
    """Resolve each declaration to its last checked contract writer."""
    blocks, targets = traceability.compile_contract_plan(ROOT, IMPLEMENTATION_CONTRACTS)
    known_blocks = {block.block_id for block in blocks}
    positions = _checked_block_order()
    latest: dict[tuple[str, str], ContractTarget] = {}

    for target in targets:
        identity = (target.target.path, target.target.symbol)
        if identity not in identities or target.block_id not in positions:
            continue
        assert target.block_id in known_blocks, target.block_id
        current = latest.get(identity)
        if current is None or positions[target.block_id] > positions[current.block_id]:
            latest[identity] = target

    assert latest.keys() == identities
    return latest


def _comparable_declaration(payload: bytes) -> ast.AST | None:
    """Return a top-level declaration whose syntax can be compared directly."""
    tree = ast.parse(payload)
    if len(tree.body) != 1 or not isinstance(tree.body[0], _COMPARABLE_DECLARATIONS):
        return None
    return tree.body[0]


def test_external_input_contract_targets_match_latest_implementation() -> None:
    """Compare Phase 3 declarations with their latest checked contract writer."""
    _, phase_targets = traceability.compile_contract_plan(ROOT, (EXTERNAL_INPUT_ROOTS,))
    identities = {
        (target.target.path, target.target.symbol) for target in phase_targets
    }
    latest = _latest_checked_targets(identities)

    # Phase 5 legitimately supersedes the Phase 3 and Phase 4 TrainSpec payloads.
    assert latest[("src/viper/stages.py", "TrainSpec")].block_id == "P5-AIR-04"

    compared: set[str] = set()
    for target in latest.values():
        target_name = f"{target.target.path}:{target.target.symbol}"
        if target.action == "remove":
            assert target.target.symbol not in traceability._python_symbols(
                ROOT / target.target.path
            ), target_name
            continue
        if "." in target.target.symbol:
            continue

        expected_payload = declaration_payload(ROOT, target)
        assert expected_payload is not None, target_name
        expected = _comparable_declaration(expected_payload)
        if expected is None:
            continue
        actual_payload = extract_declaration_bytes(
            (ROOT / target.target.path).read_bytes(),
            target.target.symbol,
        )
        actual = _comparable_declaration(actual_payload)
        assert actual is not None, target_name
        assert ast.dump(actual, include_attributes=False) == ast.dump(
            expected,
            include_attributes=False,
        ), target_name
        compared.add(target_name)

    assert {
        "src/viper/inputs.py:ExternalInputRef",
        "src/viper/execution/_materialization.py:capture_external_input",
        "src/viper/_verification/attempt.py:verify_external_inputs",
        "tests/test_run_execution.py:test_attempt_rechecks_and_publishes_captured_local_inputs",
    } <= compared
