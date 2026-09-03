"""Launch child processes without calling ``fork()`` on macOS."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as _stdlib_subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

_Text = TypeVar("_Text", str, bytes)
_BRIDGE_ARGUMENT = "--viper-spawn-bridge"


def _use_spawn_bridge() -> bool:
    """Return whether this interpreter must avoid ``fork()`` child creation."""
    return sys.platform == "darwin"


def _command_arguments(command: Sequence[str | os.PathLike[str]]) -> tuple[str, ...]:
    """Return one nonempty string argument vector."""
    arguments = tuple(os.fsdecode(argument) for argument in command)
    if not arguments:
        raise ValueError("child command must contain an executable")
    return arguments


def _resolve_executable(
    executable: str,
    *,
    cwd: str | os.PathLike[str] | None,
    environment: Mapping[str, str] | None,
) -> str:
    """Resolve the target executable before starting the macOS bridge."""
    if os.path.dirname(executable):
        path = Path(executable)
        if not path.is_absolute():
            path = Path.cwd() / path if cwd is None else Path(cwd) / path
        resolved = path.absolute()
        if not resolved.is_file():
            raise FileNotFoundError(executable)
        return str(resolved)
    search_path = None if environment is None else environment.get("PATH")
    resolved = shutil.which(executable, path=search_path)
    if resolved is None:
        raise FileNotFoundError(executable)
    return str(Path(resolved).absolute())


def _bridge_command(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None,
    environment: Mapping[str, str] | None,
    start_new_session: bool,
) -> tuple[str, ...]:
    """Encode one target command for the spawn-safe bridge process."""
    arguments = _command_arguments(command)
    arguments = (
        _resolve_executable(
            arguments[0],
            cwd=cwd,
            environment=environment,
        ),
        *arguments[1:],
    )
    payload = json.dumps(
        {
            "arguments": arguments,
            "cwd": None if cwd is None else os.fsdecode(cwd),
            "start_new_session": start_new_session,
        },
        separators=(",", ":"),
    )
    return (
        str(Path(sys.executable).absolute()),
        "-m",
        __name__,
        _BRIDGE_ARGUMENT,
        payload,
    )


class Popen(_stdlib_subprocess.Popen[_Text]):
    """Start a child through the macOS spawn bridge or the native platform path."""

    def __init__(
        self,
        args: Sequence[str | os.PathLike[str]],
        *popenargs: Any,
        **kwargs: Any,
    ) -> None:
        """Preserve ``subprocess.Popen`` behavior for VIPER's supported options."""
        original_arguments = _command_arguments(args)
        if _use_spawn_bridge():
            if kwargs.get("shell", False):
                raise ValueError("spawn-safe child commands require shell=False")
            if kwargs.get("preexec_fn") is not None:
                raise ValueError("spawn-safe child commands do not accept preexec_fn")
            if kwargs.get("pass_fds"):
                raise ValueError("spawn-safe child commands do not accept pass_fds")
            if kwargs.get("executable") is not None:
                raise ValueError("spawn-safe child commands do not accept executable")
            cwd = kwargs.pop("cwd", None)
            environment = kwargs.get("env")
            start_new_session = bool(kwargs.pop("start_new_session", False))
            args = _bridge_command(
                original_arguments,
                cwd=cwd,
                environment=environment,
                start_new_session=start_new_session,
            )
            kwargs["close_fds"] = False
        super().__init__(args, *popenargs, **kwargs)
        self.args = original_arguments


def run(
    command: Sequence[str | os.PathLike[str]],
    *,
    input: _Text | None = None,
    capture_output: bool = False,
    timeout: float | None = None,
    check: bool = False,
    **kwargs: Any,
) -> _stdlib_subprocess.CompletedProcess[_Text]:
    """Run one command through :class:`Popen` and return its completed result."""
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kwargs["stdin"] = _stdlib_subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr may not be used with capture_output")
        kwargs["stdout"] = _stdlib_subprocess.PIPE
        kwargs["stderr"] = _stdlib_subprocess.PIPE

    with Popen(command, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except _stdlib_subprocess.TimeoutExpired as error:
            process.kill()
            if sys.platform == "win32":
                error.stdout, error.stderr = process.communicate()
            else:
                process.wait()
            raise
        except BaseException:
            process.kill()
            process.wait()
            raise
        return_code = process.poll()
        if return_code is None:
            raise RuntimeError("child process completed without a return code")
        if check and return_code:
            raise _stdlib_subprocess.CalledProcessError(
                return_code,
                process.args,
                output=stdout,
                stderr=stderr,
            )
    return _stdlib_subprocess.CompletedProcess(
        process.args,
        return_code,
        stdout,
        stderr,
    )


def __getattr__(name: str) -> Any:
    """Expose standard subprocess constants and exception classes to callers."""
    return getattr(_stdlib_subprocess, name)


def _close_inherited_descriptors() -> None:
    """Close inheritable descriptors not assigned to standard streams."""
    descriptor_root = Path("/dev/fd")
    if not descriptor_root.is_dir():
        return
    for name in os.listdir(descriptor_root):
        if not name.isdigit():
            continue
        descriptor = int(name)
        if descriptor <= 2:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass


def _exec_bridge(payload: str) -> None:
    """Apply target process settings and replace the bridge with that target."""
    decoded = json.loads(payload)
    arguments = tuple(str(argument) for argument in decoded["arguments"])
    if decoded["start_new_session"]:
        os.setsid()
    if decoded["cwd"] is not None:
        os.chdir(decoded["cwd"])
    _close_inherited_descriptors()
    os.execve(arguments[0], arguments, os.environ)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != _BRIDGE_ARGUMENT:
        raise SystemExit("invalid spawn-bridge invocation")
    _exec_bridge(sys.argv[2])
