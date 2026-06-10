"""macOS launchd plist 安装与卸载."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from stock_news.common.scheduler.config import ScheduleFile, parse_duration

LABEL = "com.stock-news.schedule"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def resolve_sn_executable() -> str:
    resolved = shutil.which("sn")
    if resolved:
        return resolved
    argv0 = Path(sys.argv[0])
    if argv0.exists():
        return str(argv0.resolve())
    raise RuntimeError("找不到 sn 可执行文件，请先 uv tool install . 或用 uv run sn")


def _path_env() -> str:
    return os.environ.get(
        "PATH",
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    )


def write_plist(schedule: ScheduleFile, sn_executable: str | None = None) -> Path:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    schedule.log_path.mkdir(parents=True, exist_ok=True)
    sn_path = sn_executable or resolve_sn_executable()
    payload = {
        "Label": LABEL,
        "ProgramArguments": [sn_path, "schedule", "tick", "--quiet"],
        "StartInterval": parse_duration(schedule.tick_interval),
        "RunAtLoad": True,
        "StandardOutPath": str(schedule.log_path / "launchd.log"),
        "StandardErrorPath": str(schedule.log_path / "launchd.err.log"),
        "EnvironmentVariables": {"PATH": _path_env()},
    }
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(payload, f)
    return PLIST_PATH


def is_loaded() -> bool:
    completed = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return False
    return LABEL in completed.stdout


def load_plist(path: Path = PLIST_PATH) -> None:
    completed = subprocess.run(
        ["launchctl", "load", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())


def unload_plist(path: Path = PLIST_PATH) -> None:
    completed = subprocess.run(
        ["launchctl", "unload", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 and path.exists():
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())


def install(schedule: ScheduleFile) -> Path:
    path = write_plist(schedule)
    if is_loaded():
        unload_plist(path)
    load_plist(path)
    return path


def uninstall() -> bool:
    existed = PLIST_PATH.exists()
    if is_loaded():
        unload_plist(PLIST_PATH)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return existed
