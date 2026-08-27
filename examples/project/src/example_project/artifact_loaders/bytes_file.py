"""Load one artifact as uninterpreted bytes."""

from pathlib import Path


def load(path: Path) -> bytes:
    """Return the exact bytes stored at ``path``."""
    return path.read_bytes()
