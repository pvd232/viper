"""Execute the public CPU quickstart shown in the repository README."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from viper import _subprocess as subprocess
from viper.resume import load_resume_state


def _run(root: Path, *command: str) -> subprocess.CompletedProcess[str]:
    """Run one command in the temporary quickstart repository."""
    return subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_cpu_quickstart_executes_and_verifies_one_run(tmp_path: Path) -> None:
    """Produce the successful terminal result promised by the README."""
    root = tmp_path / "quickstart"
    (root / "examples" / "data").mkdir(parents=True)
    shutil.copy("examples/cpu_quickstart.py", root / "examples/cpu_quickstart.py")
    shutil.copy("examples/data/tiny.csv", root / "examples/data/tiny.csv")
    shutil.copy("pyproject.toml", root / "pyproject.toml")
    (root / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )

    _run(root, "git", "init", "--quiet")
    _run(root, "git", "config", "user.email", "viper@example.com")
    _run(root, "git", "config", "user.name", "VIPER Quickstart")
    _run(root, "git", "remote", "add", "origin", "https://github.com/example/viper")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "--quiet", "-m", "quickstart source")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    completed = subprocess.run(
        (sys.executable, "examples/cpu_quickstart.py"),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "status: succeeded" in completed.stdout
    assert 'model: {"weight": 1.999' in completed.stdout
    result_line = next(
        line for line in completed.stdout.splitlines() if line.startswith("result: ")
    )
    result_path = root / result_line.removeprefix("result: ")
    assert result_path.is_file()
    measurements = [
        json.loads(line)
        for line in (
            result_path.parent / "attempts/1/measurements/train.training_loss.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    assert [item["epoch"] for item in measurements] == list(range(1, 21))
    assert [item["step"] for item in measurements] == list(range(1, 21))
    # For x=(1,2,3), y=2x, each update scales the residual by 8/15.
    expected_losses = [(56 / 3) * (8 / 15) ** (2 * epoch) for epoch in range(20)]
    assert [item["value"] for item in measurements] == pytest.approx(
        expected_losses, rel=1e-8, abs=1e-14
    )
    checkpoint = load_resume_state(
        result_path.parent / "artifacts/train/resume_state/resume_state.pt"
    )
    assert checkpoint.optimizer_state["loss"] == measurements[-1]["value"]
