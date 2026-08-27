"""Load one file artifact as exact bytes."""

from pathlib import Path


def load(path: Path) -> bytes:
    """Return the complete file contents."""
    return path.read_bytes()
