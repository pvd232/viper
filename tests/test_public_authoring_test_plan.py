"""Validate the dormant acceptance tests for the public authoring PairBlocks."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_ROOT = ROOT / "plans/v0.1.0a3-public-authoring"
PLAN_PATH = PLAN_ROOT / "plan.json"
CHECKLIST_PATH = (
    ROOT / "docs/development/v0.1.0a3-public-authoring-contract.checklist.json"
)


def _constant(module: ast.Module, name: str) -> object:
    """Read one literal module-level metadata value."""
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    raise AssertionError(f"planned test is missing {name}")


def test_public_authoring_test_plan_matches_master_checklist() -> None:
    """Keep planned tests in the same dependency order as their PairBlocks."""
    plan = json.loads(PLAN_PATH.read_text())
    checklist = json.loads(CHECKLIST_PATH.read_text())
    planned = [
        (block["pair_block_id"], block["requirement_id"], block["depends_on"])
        for block in plan["blocks"]
    ]
    checklist_dependencies = {
        requirement["requirement_id"]: requirement["depends_on"]
        for requirement in checklist["requirements"]
    }
    expected = [
        (
            block["pair_block_id"],
            block["requirement_ids"][0],
            checklist_dependencies[block["requirement_ids"][0]],
        )
        for block in checklist["pair_blocks"]
        if block["requirement_ids"][0] not in {"PAC-08", "PAC-09"}
    ]
    assert planned == expected


def test_master_checklist_binds_the_current_contract_bytes() -> None:
    """Reject a checklist whose approved contract digest is stale."""
    checklist = json.loads(CHECKLIST_PATH.read_text())
    contract = checklist["contracts"][0]
    contract_path = ROOT / contract["path"]
    assert hashlib.sha256(contract_path.read_bytes()).hexdigest() == contract["sha256"]


def test_each_planned_file_is_executable_owned_test_source() -> None:
    """Reject placeholders, skips, and test source assigned to the wrong block."""
    plan = json.loads(PLAN_PATH.read_text())
    all_test_names: set[str] = set()
    for block in plan["blocks"]:
        source_path = ROOT / block["source"]
        assert source_path.is_file()
        source = source_path.read_text()
        module = ast.parse(source, filename=str(source_path))
        compile(module, str(source_path), "exec")
        assert _constant(module, "PAIR_BLOCK_ID") == block["pair_block_id"]
        assert _constant(module, "REQUIREMENT_ID") == block["requirement_id"]
        assert _constant(module, "PLANNED_DESTINATION") == block["planned_destination"]
        assert "pytest.mark.skip" not in source
        assert "pytest.mark.xfail" not in source
        assert "pytest.importorskip" not in source
        tests = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        }
        assert tests
        assert not all_test_names & tests
        all_test_names.update(tests)


def test_plan_documents_activation_without_running_dormant_tests() -> None:
    """Keep future tests out of the active suite until their owning block starts."""
    readme = (PLAN_ROOT / "README.md").read_text()
    assert "Move its planned file" in readme
    assert "confirm the relevant tests fail" in readme
    assert "temporary `xfail`" in readme


def test_first_pair_block_has_an_executable_boundary() -> None:
    """Make PAC-01 activatable without discovering scope or gates mid-block."""
    plan = json.loads(PLAN_PATH.read_text())
    first = plan["blocks"][0]
    assert first["pair_block_id"] == "P0-PAC-01"
    assert first["activation"] == {
        "tier": "contract",
        "domain": "domain_protocol",
    }
    assert first["planned_destination"] in first["allowed_paths"]
    assert "tests/conftest.py" in first["allowed_paths"]
    assert first["focused_gate"][:4] == [
        ".venv/bin/python",
        "-m",
        "pytest",
        "-q",
    ]
    assert first["planned_destination"] in first["focused_gate"]
