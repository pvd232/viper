"""Tests for user-owned artifact-loader examples."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from example_project.artifact_loaders.json_file import load


class ExampleJSONLoaderTests(unittest.TestCase):
    """Verify one project-defined loader using a format chosen by its author."""

    def test_loader_returns_json_value(self) -> None:
        """Return the value encoded by a user-owned JSON artifact."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.json"
            value = {"prediction_ids": ["one", "two"], "values": [0.25, 0.75]}
            path.write_text(json.dumps(value), encoding="utf-8")

            loaded = load(path)

        self.assertEqual(loaded, value)
