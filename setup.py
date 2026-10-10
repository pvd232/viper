"""Render repository README links for the versioned package-index description."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from setuptools import setup

_ROOT = Path(__file__).parent
_PROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
_BASE = f"https://github.com/pvd232/viper/blob/v{_PROJECT['version']}/"
_LINK = re.compile(r"(?P<label>\[[^\]\n]*\])\((?P<target>[^)\s]+)\)")


def _published_link(match: re.Match[str]) -> str:
    """Resolve file links against the release tag and preserve external URLs."""
    target = match["target"]
    if urlsplit(target).scheme or target.startswith(("#", "/")):
        return match[0]
    return f"{match['label']}({urljoin(_BASE, target)})"


setup(
    long_description=_LINK.sub(
        _published_link, (_ROOT / "README.md").read_text(encoding="utf-8")
    ),
    long_description_content_type="text/markdown",
)
