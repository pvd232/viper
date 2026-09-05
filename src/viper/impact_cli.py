"""Serve precomputed impact indexes without importing the VIPER application."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class WorklistError(ValueError):
    """Report an invalid or stale precomputed worklist."""


def _load(path: Path) -> dict[str, Any]:
    """Load and bind one worklist to its exact obligation bytes."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorklistError(f"cannot load worklist: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        raise WorklistError("unsupported worklist schema")
    if document.get("coordinate_system") != "line_one_based_column_utf8_zero_based":
        raise WorklistError("unsupported worklist coordinate system")
    obligations_file = document.get("obligations_file")
    expected_sha256 = document.get("obligations_sha256")
    if not isinstance(obligations_file, str) or not isinstance(expected_sha256, str):
        raise WorklistError("worklist provenance is incomplete")
    obligations_path = path.parent / obligations_file
    try:
        actual_sha256 = hashlib.sha256(obligations_path.read_bytes()).hexdigest()
    except OSError as error:
        raise WorklistError(f"cannot load obligations: {error}") from error
    if actual_sha256 != expected_sha256:
        raise WorklistError("worklist obligations digest differs")
    sites = document.get("sites")
    total = document.get("total")
    if not isinstance(sites, list) or total != len(sites) or not sites:
        raise WorklistError("worklist sites are incomplete")
    batches = document.get("batches")
    if not isinstance(batches, list) or not batches:
        raise WorklistError("worklist edit batches are incomplete")
    return document


def _site_line(index: int, site: object) -> str:
    """Render one validated source site."""
    if not isinstance(site, dict):
        raise WorklistError("worklist site is not an object")
    dependent = site.get("dependent")
    if not isinstance(dependent, dict):
        raise WorklistError("worklist dependent is not an object")
    values = (
        site.get("path"),
        site.get("line"),
        site.get("column"),
        site.get("kind"),
        dependent.get("symbol"),
    )
    if (
        not isinstance(values[0], str)
        or not isinstance(values[1], int)
        or not isinstance(values[2], int)
        or not isinstance(values[3], str)
        or not isinstance(values[4], str)
    ):
        raise WorklistError("worklist site fields are invalid")
    return f"{index}. {values[0]}:{values[1]}:{values[2]} {values[3]} in {values[4]}"


def _batch_lines(document: dict[str, Any]) -> list[str]:
    """Render exact token replacements grouped into one operation per file."""
    old_target = document.get("old_target")
    new_target = document.get("new_target")
    batches = document["batches"]
    if not isinstance(old_target, dict) or not isinstance(new_target, dict):
        raise WorklistError("worklist rename targets are incomplete")
    old_symbol = old_target.get("symbol")
    new_symbol = new_target.get("symbol")
    if not isinstance(old_symbol, str) or not isinstance(new_symbol, str):
        raise WorklistError("worklist rename symbols are invalid")
    lines = [
        f"Rename: {old_symbol} -> {new_symbol}",
        f"Batch edits: {len(batches)} files",
    ]
    for index, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict):
            raise WorklistError("worklist batch is not an object")
        path = batch.get("path")
        edits = batch.get("edits")
        if not isinstance(path, str) or not isinstance(edits, list) or not edits:
            raise WorklistError("worklist batch fields are invalid")
        locations = []
        for edit in edits:
            if not isinstance(edit, dict):
                raise WorklistError("worklist edit is not an object")
            line = edit.get("line")
            column = edit.get("column")
            if not isinstance(line, int) or not isinstance(column, int):
                raise WorklistError("worklist edit location is invalid")
            locations.append(f"{line}:{column}")
        lines.append(f"{index}. {path} at {','.join(locations)}")
    covered = document.get("covered_without_text_edit")
    if not isinstance(covered, int) or covered < 0:
        raise WorklistError("worklist covered-reference count is invalid")
    lines.append(f"Alias-bound references requiring no direct edit: {covered}")
    lines.append("Apply all file batches before validation.")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Read one page from a precomputed index without writing repository state."""
    parser = argparse.ArgumentParser(prog="viper-impact")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--references",
        action="store_true",
        help="render individual semantic references instead of file batches",
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.offset < 0 or not 1 <= arguments.limit <= 200:
            raise WorklistError("offset or limit is outside the supported range")
        document = _load(arguments.index.resolve())
        all_sites = document["sites"]
        sites = all_sites[arguments.offset : arguments.offset + arguments.limit]
        if arguments.json_output:
            result = {
                "status": "ok",
                "total": document["total"],
                "offset": arguments.offset,
                "sites": sites,
                "batches": document["batches"],
                "covered_without_text_edit": document["covered_without_text_edit"],
                "coordinate_system": document["coordinate_system"],
            }
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        elif not arguments.references:
            print("\n".join(_batch_lines(document)))
        else:
            end = arguments.offset + len(sites)
            start = arguments.offset + 1 if sites else 0
            print(f"References: {start}-{end}/{document['total']}")
            for index, site in enumerate(sites, start=arguments.offset + 1):
                print(_site_line(index, site))
    except WorklistError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
