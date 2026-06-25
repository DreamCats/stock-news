"""项目进程内 scheduler 循环."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from stock_news.common.scheduler.config import (
    ScheduleFile,
    load_schedule,
    parse_duration,
)
from stock_news.common.scheduler.engine import TickSummary, tick
from stock_news.common.scheduler.lock import FileLock, LockBusy

SCHEDULER_LOCK_NAME = "scheduler.lock"
SCHEDULER_PID_NAME = "scheduler.pid"
SCHEDULER_LOG_NAME = "scheduler.log"
SCHEDULER_ERR_LOG_NAME = "scheduler.err.log"


class SchedulerAlreadyRunning(RuntimeError):
    """项目级 scheduler 已经在运行."""


class SchedulerStopTimeout(RuntimeError):
    """scheduler 停止超时."""


@dataclass(frozen=True)
class SchedulerStatus:
    running: bool
    pid: int | None
    pid_running: bool
    stale_pid: bool


def scheduler_lock_path(schedule: ScheduleFile) -> Path:
    return schedule.lock_path / SCHEDULER_LOCK_NAME


def scheduler_pid_path(schedule: ScheduleFile) -> Path:
    return schedule.state_path.parent / SCHEDULER_PID_NAME


def scheduler_stdout_path(schedule: ScheduleFile) -> Path:
    return schedule.log_path / SCHEDULER_LOG_NAME


def scheduler_stderr_path(schedule: ScheduleFile) -> Path:
    return schedule.log_path / SCHEDULER_ERR_LOG_NAME


def is_scheduler_running(schedule: ScheduleFile) -> bool:
    try:
        with FileLock(scheduler_lock_path(schedule)):
            return False
    except LockBusy:
        return True


def read_scheduler_pid(schedule: ScheduleFile) -> int | None:
    path = scheduler_pid_path(schedule)
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def write_scheduler_pid(schedule: ScheduleFile, pid: int) -> None:
    path = scheduler_pid_path(schedule)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def clear_scheduler_pid(
    schedule: ScheduleFile, *, expected_pid: int | None = None
) -> None:
    path = scheduler_pid_path(schedule)
    if not path.exists():
        return
    if expected_pid is not None and read_scheduler_pid(schedule) != expected_pid:
        return
    path.unlink()


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def scheduler_status(schedule: ScheduleFile) -> SchedulerStatus:
    running = is_scheduler_running(schedule)
    pid = read_scheduler_pid(schedule)
    pid_running = is_process_running(pid) if pid is not None else False
    return SchedulerStatus(
        running=running,
        pid=pid,
        pid_running=pid_running,
        stale_pid=pid is not None and (not running or not pid_running),
    )


def resolve_sn_executable() -> str:
    argv0 = Path(sys.argv[0])
    if argv0.exists():
        return str(argv0.resolve())
    resolved = shutil.which("sn")
    if resolved:
        return resolved
    raise RuntimeError("找不到 sn 可执行文件，请先 uv tool install . 或用 uv run sn")


def start_scheduler_process(
    schedule: ScheduleFile,
    *,
    cwd: Path | None = None,
    sn_executable: str | None = None,
    startup_wait_seconds: float = 2.0,
) -> SchedulerStatus:
    schedule.log_path.mkdir(parents=True, exist_ok=True)
    schedule.lock_path.mkdir(parents=True, exist_ok=True)
    schedule.state_path.parent.mkdir(parents=True, exist_ok=True)
    status = scheduler_status(schedule)
    if status.running:
        return status
    if status.stale_pid:
        clear_scheduler_pid(schedule)

    stdout_path = scheduler_stdout_path(schedule)
    stderr_path = scheduler_stderr_path(schedule)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sn_executable or resolve_sn_executable(),
        "schedule",
        "serve",
        "--quiet",
    ]

    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(cwd or Path.cwd()),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    write_scheduler_pid(schedule, process.pid)
    deadline = time.monotonic() + startup_wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            clear_scheduler_pid(schedule, expected_pid=process.pid)
            raise RuntimeError(
                f"project scheduler 启动失败，详见 {scheduler_stderr_path(schedule)}"
            )
        if is_scheduler_running(schedule):
            return scheduler_status(schedule)
        time.sleep(0.05)
    return scheduler_status(schedule)


def stop_scheduler_process(
    schedule: ScheduleFile,
    *,
    timeout_seconds: float = 30.0,
    force: bool = False,
) -> SchedulerStatus:
    status = scheduler_status(schedule)
    if status.stale_pid:
        clear_scheduler_pid(schedule)
        return scheduler_status(schedule)
    if not status.running:
        return status
    if status.pid is None or not status.pid_running:
        return status

    try:
        os.kill(status.pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_scheduler_pid(schedule, expected_pid=status.pid)
        return scheduler_status(schedule)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_process_running(status.pid) or not is_scheduler_running(schedule):
            clear_scheduler_pid(schedule, expected_pid=status.pid)
            return scheduler_status(schedule)
        time.sleep(0.2)

    if force:
        try:
            os.killpg(status.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        clear_scheduler_pid(schedule, expected_pid=status.pid)
        return scheduler_status(schedule)
    raise SchedulerStopTimeout(str(status.pid))


def run_scheduler_loop(
    *,
    load_fn: Callable[[], ScheduleFile] | None = None,
    on_start: Callable[[ScheduleFile, Path], None] | None = None,
    on_tick: Callable[[TickSummary], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    load = load_fn or (lambda: load_schedule(create_if_missing=True))
    initial_schedule = load()
    lock_path = scheduler_lock_path(initial_schedule)

    try:
        with FileLock(lock_path):
            if on_start:
                on_start(initial_schedule, lock_path)
            while not _should_stop(should_stop):
                started = time.monotonic()
                schedule = load()
                summary = tick(schedule)
                if on_tick:
                    on_tick(summary)
                elapsed = time.monotonic() - started
                sleep_seconds = max(
                    0.0, parse_duration(schedule.tick_interval) - elapsed
                )
                _sleep_until_next_tick(sleep_seconds, should_stop, sleep_fn)
    except LockBusy as exc:
        raise SchedulerAlreadyRunning(str(lock_path)) from exc


def _should_stop(should_stop: Callable[[], bool] | None) -> bool:
    return bool(should_stop and should_stop())


def _sleep_until_next_tick(
    seconds: float,
    should_stop: Callable[[], bool] | None,
    sleep_fn: Callable[[float], None],
) -> None:
    deadline = time.monotonic() + seconds
    while not _should_stop(should_stop):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        sleep_fn(min(remaining, 1.0))
