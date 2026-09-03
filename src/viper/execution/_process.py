"""Execute project commands through the VIPER worker interface."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import _subprocess as subprocess


class WorkerError(RuntimeError):
    """Report a rejected, timed-out, or failed worker invocation."""


class ExecutionPolicy(BaseModel):
    """Select the worker backend and process limits for one invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Literal["trusted_local"] = "trusted_local"
    timeout_seconds: float | None = Field(default=None, gt=0)


class WorkerRequest(BaseModel):
    """Describe one project command and its bounded local context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_root: Path
    working_directory: Path
    context_path: Path
    command: tuple[str, ...] = Field(min_length=1)
    environment: dict[str, str] = Field(default_factory=dict)
    policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @model_validator(mode="after")
    def validate_paths(self) -> WorkerRequest:
        """Keep the context and working directory beneath the workspace root."""
        root = self.workspace_root.resolve()
        for path in (self.working_directory, self.context_path):
            if not path.resolve().is_relative_to(root):
                raise ValueError("worker path escapes the workspace root")
        return self


class WorkerResult(BaseModel):
    """Record the observable result of one worker process."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        ser_json_bytes="base64",
    )

    backend: Literal["trusted_local"] = "trusted_local"
    command: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    returncode: int
    stdout: bytes
    stderr: bytes


def execute_worker(request: WorkerRequest) -> WorkerResult:
    """Execute one command in the caller's trust boundary."""
    request.working_directory.mkdir(parents=True, exist_ok=True)
    if not request.context_path.is_file():
        raise WorkerError("worker context file is missing")
    environment = os.environ.copy()
    environment.update(request.environment)
    environment["VIPER_CONTEXT_PATH"] = str(request.context_path)
    started_at = datetime.now(UTC)
    try:
        process = subprocess.run(
            request.command,
            cwd=request.working_directory,
            env=environment,
            capture_output=True,
            timeout=request.policy.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerError("worker command exceeded its timeout") from exc
    completed_at = datetime.now(UTC)
    result = WorkerResult(
        command=request.command,
        started_at=started_at,
        completed_at=completed_at,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )
    if result.returncode != 0:
        raise WorkerError(f"worker command exited with status {result.returncode}")
    return result
