"""调度后台进程管理。

这里用 pid 文件托管项目自己的 schedule serve 进程，不接系统服务管理器。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SchedulerServerStatus:
    """调度后台进程状态。"""

    running: bool
    pid: int | None
    pid_file: str
    log_file: str
    message: str


def scheduler_server_status(
    *,
    pid_file: str | Path,
    log_file: str | Path,
) -> SchedulerServerStatus:
    """读取后台进程状态。"""

    pid_path = Path(pid_file).expanduser()
    log_path = Path(log_file).expanduser()
    info = _read_pid_info(pid_path)
    pid = _pid_from_info(info)
    if pid is None:
        return _status(False, None, pid_path, log_path, "未运行")
    if not _is_process_alive(pid):
        return _status(False, pid, pid_path, log_path, "pid 文件存在，但进程已退出")
    if not _looks_like_scheduler(pid):
        return _status(False, pid, pid_path, log_path, "pid 指向的不是调度进程")
    return _status(True, pid, pid_path, log_path, "运行中")


def start_scheduler_server(
    *,
    pid_file: str | Path,
    log_file: str | Path,
    command: list[str],
) -> SchedulerServerStatus:
    """后台启动 schedule serve。"""

    pid_path = Path(pid_file).expanduser()
    log_path = Path(log_file).expanduser()
    current = scheduler_server_status(pid_file=pid_path, log_file=log_path)
    if current.running:
        return current

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    log_path.chmod(0o600)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().astimezone().isoformat()}] start scheduler\n")
        log.flush()
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    _write_pid_info(
        pid_path,
        {
            "pid": process.pid,
            "started_at": datetime.now().astimezone().isoformat(),
            "command": command,
            "log_file": str(log_path),
        },
    )
    return scheduler_server_status(pid_file=pid_path, log_file=log_path)


def stop_scheduler_server(
    *,
    pid_file: str | Path,
    log_file: str | Path,
    timeout_seconds: float = 10.0,
) -> SchedulerServerStatus:
    """停止后台 schedule serve。"""

    pid_path = Path(pid_file).expanduser()
    log_path = Path(log_file).expanduser()
    current = scheduler_server_status(pid_file=pid_path, log_file=log_path)
    if not current.running or current.pid is None:
        _remove_pid_file(pid_path)
        return _status(False, current.pid, pid_path, log_path, "未运行")

    os.kill(current.pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_process_alive(current.pid):
            _remove_pid_file(pid_path)
            return _status(False, current.pid, pid_path, log_path, "已停止")
        time.sleep(0.1)

    os.kill(current.pid, signal.SIGKILL)
    _remove_pid_file(pid_path)
    return _status(False, current.pid, pid_path, log_path, "已强制停止")


def _read_pid_info(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_pid_info(path: Path, data: dict[str, object]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _pid_from_info(info: dict[str, object]) -> int | None:
    pid = info.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    return pid


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _looks_like_scheduler(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True
    command = result.stdout.strip()
    if not command:
        return False
    return "stock_news" in command and "schedule" in command and "serve" in command


def _remove_pid_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _status(
    running: bool,
    pid: int | None,
    pid_file: Path,
    log_file: Path,
    message: str,
) -> SchedulerServerStatus:
    return SchedulerServerStatus(
        running=running,
        pid=pid,
        pid_file=str(pid_file),
        log_file=str(log_file),
        message=message,
    )
