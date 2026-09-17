"""Tests for the installed VIPER command surface."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import viper.runtime as runtime
from viper import _subprocess as subprocess
from viper.cli import main
from viper.journal import DurableJournal


class _Distribution:
    """Supply installed-distribution metadata for CLI diagnosis tests."""

    def __init__(self, version: str, root: Path) -> None:
        self.metadata = {"Name": "cffi"}
        self.version = version
        self.root = root

    def locate_file(self, path: str) -> Path:
        """Resolve a package-relative path below the test installation root."""
        return self.root / path


def test_env_doctor_reports_active_interpreter(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    """Return a structured healthy report without starting a run."""
    root = tmp_path / "site-packages"
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "distributions",
        lambda: (_Distribution("1.17.0", root),),
    )
    monkeypatch.setattr(runtime.sys, "executable", str(tmp_path / "bin/python"))
    monkeypatch.setattr(runtime.sys, "path", [str(root)])

    status = main(["--json", "env", "doctor"])
    result = json.loads(capsys.readouterr().out)

    assert status == 0
    assert result["status"] == "ok"
    assert result["operation"] == "env_doctor"
    assert result["diagnosis"]["healthy"] is True
    assert result["diagnosis"]["interpreter"] == str(tmp_path / "bin/python")


def test_env_doctor_fails_with_duplicate_distribution_evidence(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    """Return every conflicting installation and a nonzero CLI status."""
    roots = (tmp_path / "first-site", tmp_path / "second-site")
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "distributions",
        lambda: (
            _Distribution("1.16.0", roots[0]),
            _Distribution("1.17.0", roots[1]),
        ),
    )
    monkeypatch.setattr(runtime.sys, "executable", str(tmp_path / "bin/python"))
    monkeypatch.setattr(runtime.sys, "path", [str(root) for root in roots])
    expected = runtime.diagnose_python_env().model_dump(mode="json")

    status = main(["--json", "env", "doctor"])
    result = json.loads(capsys.readouterr().out)
    diagnosis = result["details"]["diagnosis"]

    assert status == 1
    assert result["status"] == "error"
    assert result["code"] == "execution_failed"
    assert result["operation"] == "env_doctor"
    assert diagnosis == expected
    assert diagnosis["healthy"] is False
    assert diagnosis["interpreter"] == str(tmp_path / "bin/python")
    assert diagnosis["search_paths"] == [str(root) for root in roots]
    assert diagnosis["conflicts"][0]["name"] == "cffi"
    assert {item["version"] for item in diagnosis["conflicts"][0]["installations"]} == {
        "1.16.0",
        "1.17.0",
    }
    assert {item["root"] for item in diagnosis["conflicts"][0]["installations"]} == {
        str(root) for root in roots
    }


def test_env_doctor_fails_when_no_distributions_are_installed(
    monkeypatch,
    capsys,
) -> None:
    """Expose the existing empty-environment rejection through the doctor."""
    monkeypatch.setattr(runtime.importlib.metadata, "distributions", lambda: ())

    status = main(["--json", "env", "doctor"])
    result = json.loads(capsys.readouterr().out)

    assert status == 1
    assert result["details"]["diagnosis"]["violations"] == ["no_distributions"]


def test_mcp_stdio_requires_explicit_execution_access(
    monkeypatch, tmp_path: Path
) -> None:
    """Start MCP in read mode unless the caller explicitly selects execution."""
    calls: list[tuple[str, ...]] = []

    def run(arguments, **_kwargs):
        calls.append(tuple(str(item) for item in arguments))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr("viper.cli.subprocess.run", run)

    assert main(["mcp", "--root", str(tmp_path)]) == 0
    assert calls[-1][-1] == "read"
    assert main(["mcp", "--root", str(tmp_path), "--access", "execute"]) == 0
    assert calls[-1][-1] == "execute"


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

    def test_removed_impact_command_is_not_registered(self) -> None:
        """Reject the extracted source-impact command group at the parser boundary."""
        process = subprocess.run(
            [sys.executable, "-m", "viper.cli", "--json", "impact"],
            check=False,
            capture_output=True,
        )

        self.assertEqual(process.returncode, 1)
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
            self.assertEqual(result["operation"], "init_workspace")
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
            "export-run": [
                "export-run",
                "missing-run.yaml",
                "--output",
                "bundle",
                "--trust-source",
                "https://example.test/repository",
            ],
            "env doctor": ["env", "doctor"],
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
