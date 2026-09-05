"""Tests for the installed VIPER command surface."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from viper import _subprocess as subprocess
from viper.cli import main
from viper.journal import DurableJournal


class CommandLineTests(unittest.TestCase):
    """Verify command dispatch through public authoring and validation paths."""

    def test_validate_stage_command_loads_active_example(self) -> None:
        """Validate one canonical stage file and report its stage kind."""
        path = Path(__file__).parent / "data/download_stage.yaml"
        output = StringIO()

        with redirect_stdout(output):
            status = main(["validate-stage", str(path)])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "valid download stage\n")

    def test_cli_json_success_contract(self) -> None:
        """Emit one JSON success document on standard output."""
        process = subprocess.run(
            [sys.executable, "-m", "viper.cli", "--json", "capabilities"],
            check=False,
            capture_output=True,
        )

        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stderr, b"")
        self.assertEqual(json.loads(process.stdout)["status"], "ok")

    def test_cli_json_failure_contract(self) -> None:
        """Emit one JSON parsing failure with a nonzero exit status."""
        process = subprocess.run(
            [sys.executable, "-m", "viper.cli", "--json", "unknown"],
            check=False,
            capture_output=True,
        )

        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stderr, b"")
        failure = json.loads(process.stdout)
        self.assertEqual(failure["origin"], "cli")
        self.assertEqual(failure["operation"], None)

    def test_preflight_failure_uses_nonzero_exit_status(self) -> None:
        """Return a failing exit status when plan checks find an invalid path."""
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "viper.cli",
                "--json",
                "preflight",
                "missing/spec.yaml",
            ],
            check=False,
            capture_output=True,
        )

        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stderr, b"")
        result = json.loads(process.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ready"], False)

    def test_execute_benchmark_command_routes_to_application(self) -> None:
        """Return one typed document failure for missing benchmark inputs."""
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "viper.cli",
                "--json",
                "execute-benchmark",
                "missing/resolved.yaml",
                "missing/benchmark.yaml",
            ],
            check=False,
            capture_output=True,
        )

        self.assertEqual(process.returncode, 1)
        result = json.loads(process.stdout)
        self.assertEqual(result["operation"], "execute_benchmark")
        self.assertEqual(result["code"], "not_found")

    def test_impact_explain_command_routes_to_application(self) -> None:
        """Return one typed document failure for absent impact evidence."""
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "viper.cli",
                "--json",
                "impact",
                "explain",
                "--check",
                "missing-check.json",
                "--baseline-graph",
                "missing-baseline.json",
                "--realized-graph",
                "missing-realized.json",
            ],
            check=False,
            capture_output=True,
        )

        self.assertEqual(process.returncode, 1)
        result = json.loads(process.stdout)
        self.assertEqual(result["operation"], "explain_impact")
        self.assertEqual(result["code"], "not_found")

    def test_status_command_reads_attempt_journal(self) -> None:
        """Return one attempt's latest durable state through the JSON command."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            DurableJournal(path).append(
                "allocated",
                "attempt allocated",
                recorded_at=datetime(2026, 8, 22, tzinfo=UTC),
            )
            process = subprocess.run(
                [sys.executable, "-m", "viper.cli", "--json", "status", str(path)],
                check=False,
                capture_output=True,
            )

        self.assertEqual(process.returncode, 0)
        result = json.loads(process.stdout)
        self.assertEqual(result["state"], "allocated")
        self.assertEqual(result["next_states"], ["preflighting", "terminal"])

    def test_init_command_generates_project(self) -> None:
        """Generate the starter project through the installed command surface."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "starter"
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "viper.cli",
                    "--json",
                    "init",
                    str(target),
                    "--package",
                    "sample_project",
                ],
                check=False,
                capture_output=True,
            )

            self.assertEqual(process.returncode, 0)
            result = json.loads(process.stdout)
            self.assertEqual(result["operation"], "init_project")
            self.assertTrue((target / "src/sample_project/stages/train.py").is_file())

    def test_every_command_emits_one_json_document_and_stable_exit_status(
        self,
    ) -> None:
        """Exercise every CLI route through its success or expected-failure path."""
        cases = {
            "validate-stage": ["validate-stage", "missing.yaml"],
            "validate-resolved-stage": [
                "validate-resolved-stage",
                "missing.yaml",
            ],
            "validate-run": ["validate-run", "missing.yaml"],
            "freeze-run": ["freeze-run", "missing.yaml"],
            "preflight": ["preflight", "missing.yaml"],
            "execute-stage": ["execute-stage", "missing.yaml", "train"],
            "run": ["run", "missing.yaml"],
            "retry": ["retry", "missing.yaml"],
            "execute-benchmark": [
                "execute-benchmark",
                "missing-run.yaml",
                "missing-benchmark.yaml",
            ],
            "plan-diff": ["plan-diff", "left.yaml", "right.yaml"],
            "lineage": [
                "lineage",
                "missing.yaml",
                "--trust-source",
                "https://example.test/repository",
            ],
            "status": ["status", "missing.jsonl"],
            "compare-runs": [
                "compare-runs",
                "left.yaml",
                "right.yaml",
                "--trust-source",
                "https://example.test/repository",
            ],
            "verify-run": [
                "verify-run",
                "missing.yaml",
                "--trust-source",
                "https://example.test/repository",
            ],
            "verify-benchmark": [
                "verify-benchmark",
                "missing.yaml",
                "--trust-source",
                "https://example.test/repository",
            ],
            "verify-pointer": [
                "verify-pointer",
                "missing.yaml",
                "--trust-source",
                "https://example.test/repository",
            ],
            "schema": ["schema", "MissingSchema"],
            "capabilities": ["capabilities"],
            "impact-explain": [
                "impact",
                "explain",
                "--check",
                "missing-check.json",
                "--baseline-graph",
                "missing-baseline.json",
                "--realized-graph",
                "missing-realized.json",
            ],
            "impact-analyze": [
                "impact",
                "analyze",
                "--root",
                "missing-repository",
                "--target",
                "src/example.py:target",
            ],
            "impact-rename-check": [
                "impact",
                "rename-check",
                "--root",
                "missing-repository",
                "--old",
                "src/example.py:old",
                "--new",
                "src/example.py:new",
                "--kind",
                "calls",
            ],
        }
        for name, arguments in cases.items():
            with self.subTest(command=name):
                process = subprocess.run(
                    [sys.executable, "-m", "viper.cli", "--json", *arguments],
                    check=False,
                    capture_output=True,
                )

                self.assertIn(process.returncode, {0, 1})
                self.assertEqual(process.stderr, b"")
                document = json.loads(process.stdout)
                self.assertIn(document["status"], {"ok", "error"})
                self.assertTrue(process.stdout.endswith(b"\n"))
