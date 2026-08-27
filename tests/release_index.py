"""Verify that one package index contains the exact local release files."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import urlopen


def distribution_hashes(dist_dir: Path) -> dict[str, str]:
    """Return the SHA-256 digest of every distribution in one directory."""
    files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    if not files:
        raise ValueError(f"no distribution files found in {dist_dir}")
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def published_hashes(payload: Mapping[str, Any]) -> dict[str, str]:
    """Extract filename-to-SHA-256 bindings from a package-index response."""
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise ValueError("package-index response lacks a urls list")

    result: dict[str, str] = {}
    for entry in urls:
        if not isinstance(entry, dict):
            raise ValueError("package-index urls must contain objects")
        filename = entry.get("filename")
        digests = entry.get("digests")
        sha256 = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(filename, str) or not isinstance(sha256, str):
            raise ValueError("package-index file lacks filename or SHA-256")
        result[filename] = sha256
    return result


def fetch_published_hashes(index: str, project: str, version: str) -> dict[str, str]:
    """Retrieve one version's file identities from its package-index API."""
    parsed_index = urlsplit(index)
    if parsed_index.scheme != "https" or not parsed_index.netloc:
        raise ValueError("package index must be an absolute HTTPS URL")
    endpoint = (
        f"{index.rstrip('/')}/pypi/{quote(project, safe='')}/"
        f"{quote(version, safe='')}/json"
    )
    with urlopen(endpoint, timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("package-index response must be an object")
    return published_hashes(payload)


def require_identical_files(
    local: Mapping[str, str], published: Mapping[str, str]
) -> None:
    """Require two release-file mappings to contain identical bindings."""
    if published != local:
        raise ValueError(
            "package-index files differ from local distributions: "
            f"local={dict(local)!r}, published={dict(published)!r}"
        )


def verify_package_index(
    *, index: str, project: str, version: str, dist_dir: Path
) -> None:
    """Require the package index and local directory to bind the same files."""
    local = distribution_hashes(dist_dir)
    published = fetch_published_hashes(index, project, version)
    require_identical_files(local, published)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the package-index verification command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the selected release and return a successful process status."""
    args = parse_args(argv)
    verify_package_index(
        index=args.index,
        project=args.project,
        version=args.version,
        dist_dir=args.dist,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
