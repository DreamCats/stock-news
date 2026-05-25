"""子进程执行封装."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    timed_out: bool = False


def _tail_text(value: str | bytes | None, limit: int = 2048) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    return text[-limit:]


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault(
        "PATH",
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    )
    return env


def run_command(command: str, timeout_seconds: int | None) -> CommandResult:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_command_env(),
            check=False,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            stdout_tail=_tail_text(completed.stdout),
            stderr_tail=_tail_text(completed.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            exit_code=None,
            duration_ms=duration_ms,
            stdout_tail=_tail_text(exc.stdout),
            stderr_tail=_tail_text(exc.stderr),
            timed_out=True,
        )
