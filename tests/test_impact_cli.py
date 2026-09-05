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
                "schema_version": 2,
                "coordinate_system": "line_one_based_column_utf8_zero_based",
                "obligations_file": obligations.name,
                "obligations_sha256": hashlib.sha256(
                    obligations.read_bytes()
                ).hexdigest(),
                "total": 1,
                "old_target": {"path": "src/lib.py", "symbol": "old"},
                "new_target": {"path": "src/lib.py", "symbol": "new"},
                "sites": [
                    {
                        "dependent": {"path": "src/app.py", "symbol": "caller"},
                        "kind": "calls",
                        "path": "src/app.py",
                        "line": 7,
                        "column": 4,
                        "binding_form": "module_alias",
                    }
                ],
                "batches": [
                    {
                        "path": "src/app.py",
                        "edits": [
                            {
                                "line": 7,
                                "column": 8,
                                "end_column": 11,
                                "old_text": "old",
                                "new_text": "new",
                                "reasons": ["module_alias"],
                            }
                        ],
                    }
                ],
                "covered_without_text_edit": 0,
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
        "Rename: old -> new\n"
        "Batch edits: 1 files\n"
        "1. src/app.py at 7:8\n"
        "Alias-bound references requiring no direct edit: 0\n"
        "Apply all file batches before validation.\n"
    )
    assert after == before


def test_worklist_lookup_can_render_individual_references(
    tmp_path: Path, capsys
) -> None:
    """Retain exact semantic rows for audit and diagnosis."""
    index = _index(tmp_path)

    status = main(["--index", str(index), "--references", "--limit", "1"])

    assert status == 0
    assert capsys.readouterr().out == (
        "References: 1-1/1\n1. src/app.py:7:4 calls in caller\n"
    )


def test_worklist_lookup_rejects_changed_obligations(tmp_path: Path, capsys) -> None:
    """Reject an index whose frozen obligation bytes have changed."""
    index = _index(tmp_path)
    (tmp_path / "rename-obligations.json").write_bytes(b'{"frozen":false}')

    status = main(["--index", str(index)])

    assert status == 1
    assert "digest differs" in capsys.readouterr().err
