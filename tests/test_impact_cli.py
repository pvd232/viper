"""Verify the stdlib-only precomputed impact lookup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from viper.impact_cli import main


def _index(tmp_path: Path) -> Path:
    """Write one bound worklist fixture."""
    obligations = tmp_path / "rename-obligations.json"
    obligations.write_bytes(b'{"frozen":true}')
    index = tmp_path / "rename-worklist.json"
    index.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "obligations_file": obligations.name,
                "obligations_sha256": hashlib.sha256(
                    obligations.read_bytes()
                ).hexdigest(),
                "total": 1,
                "sites": [
                    {
                        "dependent": {"path": "src/app.py", "symbol": "caller"},
                        "kind": "calls",
                        "path": "src/app.py",
                        "line": 7,
                        "column": 4,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return index


def test_worklist_lookup_reads_one_bound_page(tmp_path: Path, capsys) -> None:
    """Return source evidence without creating another artifact."""
    index = _index(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    status = main(["--index", str(index), "--limit", "1"])

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert status == 0
    assert capsys.readouterr().out == (
        "References: 1-1/1\n1. src/app.py:7:4 calls in caller\n"
    )
    assert after == before


def test_worklist_lookup_rejects_changed_obligations(tmp_path: Path, capsys) -> None:
    """Reject an index whose frozen obligation bytes have changed."""
    index = _index(tmp_path)
    (tmp_path / "rename-obligations.json").write_bytes(b'{"frozen":false}')

    status = main(["--index", str(index)])

    assert status == 1
    assert "digest differs" in capsys.readouterr().err
