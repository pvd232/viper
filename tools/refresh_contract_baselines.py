#!/usr/bin/env python3
"""Refresh or check the generated development-contract baseline manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

REQUIREMENT_PATTERN = re.compile(
    r"^\| (?P<label>[A-Z]{3}-\d{2}) "
    r"<!-- contract-requirement: (?P<requirement>[A-Z]{3}-\d{2}) ",
    re.MULTILINE,
)


class ContractBaselineError(ValueError):
    """Report an invalid or stale contract-baseline manifest."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractBaselineError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractBaselineError(f"{path}: top level must be an object")
    return value


def _contract_paths(manifest: dict[str, Any]) -> tuple[str, ...]:
    if manifest.get("schema_version") != 1:
        raise ContractBaselineError("schema_version must equal 1")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ContractBaselineError("contracts must contain at least one record")

    paths: list[str] = []
    for index, record in enumerate(contracts):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ContractBaselineError(
                f"contracts[{index}].path must be a repository-relative path"
            )
        value = record["path"]
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ContractBaselineError(
                f"contracts[{index}].path is not normalized: {value}"
            )
        paths.append(value)
    if len(paths) != len(set(paths)):
        raise ContractBaselineError("contract paths must be unique")
    return tuple(paths)


def _record(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.is_file():
        raise ContractBaselineError(f"contract does not exist: {relative_path}")
    content = path.read_bytes()
    text = content.decode("utf-8")
    requirements: list[str] = []
    for match in REQUIREMENT_PATTERN.finditer(text):
        if match.group("label") != match.group("requirement"):
            raise ContractBaselineError(
                f"{relative_path}: requirement label and marker differ"
            )
        requirements.append(match.group("requirement"))
    if not requirements:
        raise ContractBaselineError(
            f"{relative_path}: contract declares no requirements"
        )
    if len(requirements) != len(set(requirements)):
        raise ContractBaselineError(
            f"{relative_path}: requirement identifiers must be unique"
        )
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "requirement_ids": sorted(requirements),
    }


def rendered_manifest(root: Path, manifest_path: Path) -> bytes:
    """Return canonical baseline-manifest bytes for its declared contract paths."""
    manifest = _load_object(manifest_path)
    records = [_record(root, path) for path in _contract_paths(manifest)]
    owners: dict[str, str] = {}
    for record in records:
        path = str(record["path"])
        for requirement in record["requirement_ids"]:
            previous = owners.setdefault(str(requirement), path)
            if previous != path:
                raise ContractBaselineError(
                    f"requirement {requirement} belongs to {previous} and {path}"
                )
    payload = {"schema_version": 1, "contracts": records}
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    """Refresh the manifest or verify that its generated content is current."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="replace the manifest with current contract digests and requirements",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="manifest path; defaults beneath the repository root",
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    manifest_path = (
        arguments.manifest.resolve()
        if arguments.manifest is not None
        else root / "docs/development/contract-baselines.json"
    )
    display_path = (
        manifest_path.relative_to(root)
        if manifest_path.is_relative_to(root)
        else manifest_path
    )
    try:
        expected = rendered_manifest(root, manifest_path)
        if arguments.write:
            manifest_path.write_bytes(expected)
            print(f"refreshed {display_path}")
            return 0
        actual = manifest_path.read_bytes()
        if actual != expected:
            raise ContractBaselineError(
                "contract baselines are stale; run "
                "python tools/refresh_contract_baselines.py --write"
            )
    except (ContractBaselineError, OSError, ValueError) as error:
        parser.exit(1, f"contract baseline error: {error}\n")
    print(f"validated {display_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
