"""Load one JSON artifact from a user-selected repository path."""

import json
from pathlib import Path


def load(path: Path) -> object:
    """Parse and return the JSON value stored at ``path``."""
    return json.loads(path.read_text(encoding="utf-8"))
