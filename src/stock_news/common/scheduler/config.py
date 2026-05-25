"""schedule.yaml 加载与校验."""

from __future__ import annotations

import re
from datetime import datetime, time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

SCHEDULE_CONFIG_FILE = Path.home() / ".config" / "stock-news" / "schedule.yaml"
SCHEDULE_DIR = Path.home() / ".config" / "stock-news" / "schedule"

_DURATION_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[smhd])$")


class ScheduleJob(BaseModel):
    """单个调度任务."""

    id: str
    command: str
    every: str | None = None
    at: str | None = None
    active_hours: str | None = None
    timeout: str | None = None

    @model_validator(mode="after")
    def _validate_schedule(self) -> ScheduleJob:
        if bool(self.every) == bool(self.at):
            raise ValueError("job 必须且只能配置 every 或 at")
        parse_duration(self.every) if self.every else None
        parse_clock(self.at) if self.at else None
        parse_duration(self.timeout) if self.timeout else None
        if self.active_hours:
            parse_active_hours(self.active_hours)
        return self


class ScheduleFile(BaseModel):
    """schedule.yaml 顶层配置."""

    tick_interval: str = "10m"
    log_dir: str = "~/.config/stock-news/schedule/logs"
    state_file: str = "~/.config/stock-news/schedule/state.json"
    lock_dir: str = "~/.config/stock-news/schedule/locks"
    jobs: list[ScheduleJob] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_paths(self) -> ScheduleFile:
        parse_duration(self.tick_interval)
        seen: set[str] = set()
        for job in self.jobs:
            if job.id in seen:
                raise ValueError(f"重复的 schedule job id: {job.id}")
            seen.add(job.id)
        return self

    @property
    def log_path(self) -> Path:
        return Path(self.log_dir).expanduser()

    @property
    def state_path(self) -> Path:
        return Path(self.state_file).expanduser()

    @property
    def lock_path(self) -> Path:
        return Path(self.lock_dir).expanduser()

    @property
    def tick_log_path(self) -> Path:
        return self.log_path / "tick.log"


def parse_duration(value: str | int) -> int:
    """解析 10m / 1h / 30s 为秒."""
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("duration 必须大于 0")
        return value
    m = _DURATION_RE.match(value.strip())
    if not m:
        raise ValueError(f"非法 duration: {value}")
    num = int(m.group("num"))
    unit = m.group("unit")
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return num * multipliers[unit]


def parse_clock(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"非法时间格式，期望 HH:MM: {value}") from exc


def parse_active_hours(value: str) -> tuple[time, time]:
    parts = value.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"非法 active_hours，期望 HH:MM-HH:MM: {value}")
    return parse_clock(parts[0]), parse_clock(parts[1])


def is_in_active_hours(value: str | None, now: datetime) -> bool:
    if not value:
        return True
    start, end = parse_active_hours(value)
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def ensure_schedule_dirs(schedule: ScheduleFile) -> None:
    schedule.log_path.mkdir(parents=True, exist_ok=True)
    schedule.lock_path.mkdir(parents=True, exist_ok=True)
    schedule.state_path.parent.mkdir(parents=True, exist_ok=True)


def default_schedule_data() -> dict[str, Any]:
    return ScheduleFile().model_dump(mode="json")


def write_default_schedule(path: Path = SCHEDULE_CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = default_schedule_data()
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def load_schedule(
    path: Path = SCHEDULE_CONFIG_FILE,
    *,
    create_if_missing: bool = False,
) -> ScheduleFile:
    if not path.exists():
        if create_if_missing:
            write_default_schedule(path)
        else:
            return ScheduleFile()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"schedule.yaml 必须是 YAML object: {path}")
    schedule = ScheduleFile.model_validate(raw)
    ensure_schedule_dirs(schedule)
    return schedule
