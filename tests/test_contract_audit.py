"""Exercise the deterministic contract-system audit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_active_contract_stack_passes_deterministic_audit() -> None:
    """Require active contracts, protocol models, and checklist rules to agree."""
    repository_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "tests/contract_audit.py", "--root", str(repository_root)],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
