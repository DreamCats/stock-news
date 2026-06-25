"""调度状态 JSON 存储。

状态只用于项目进程内调度的可观测性和下次触发判断，不承载业务数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

TaskRunStatus = Literal["running", "success", "failed", "skipped"]


@dataclass(frozen=True)
class ScheduledTaskState:
    """单个定时任务的最近运行状态。"""

    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_status: TaskRunStatus | None = None
    last_message: str = ""


@dataclass(frozen=True)
class TaskRunRecord:
    """一次任务状态变更记录。"""

    task_id: str
    started_at: datetime
    finished_at: datetime | None
    status: TaskRunStatus
    message: str = ""


class ScheduleStateStore:
    """读写 schedule_state.json。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def load(self) -> dict[str, ScheduledTaskState]:
        """读取所有任务状态。"""

        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"调度状态必须是 JSON object: {self.path}")
        tasks = raw.get("tasks", raw)
        if not isinstance(tasks, dict):
            raise ValueError(f"调度状态 tasks 必须是 JSON object: {self.path}")
        return {
            str(task_id): _state_from_dict(item)
            for task_id, item in tasks.items()
            if isinstance(item, dict)
        }

    def get(self, task_id: str) -> ScheduledTaskState:
        """读取单个任务状态。"""

        return self.load().get(task_id, ScheduledTaskState())

    def mark_started(self, task_id: str, *, started_at: datetime) -> None:
        """记录任务开始。"""

        self.record(
            TaskRunRecord(
                task_id=task_id,
                started_at=started_at,
                finished_at=None,
                status="running",
            )
        )

    def mark_finished(
        self,
        task_id: str,
        *,
        started_at: datetime,
        finished_at: datetime,
        status: TaskRunStatus,
        message: str,
    ) -> None:
        """记录任务结束。"""

        self.record(
            TaskRunRecord(
                task_id=task_id,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                message=message,
            )
        )

    def record(self, run: TaskRunRecord) -> None:
        """写入一次任务状态变更。"""

        states = self.load()
        states[run.task_id] = ScheduledTaskState(
            last_started_at=run.started_at,
            last_finished_at=run.finished_at,
            last_status=run.status,
            last_message=run.message,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tasks": {
                task_id: _state_to_dict(state) for task_id, state in states.items()
            }
        }
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _state_from_dict(data: dict[str, Any]) -> ScheduledTaskState:
    status = data.get("last_status")
    if status not in ("running", "success", "failed", "skipped", None):
        status = None
    return ScheduledTaskState(
        last_started_at=_parse_datetime(data.get("last_started_at")),
        last_finished_at=_parse_datetime(data.get("last_finished_at")),
        last_status=status,
        last_message=str(data.get("last_message") or ""),
    )


def _state_to_dict(state: ScheduledTaskState) -> dict[str, object]:
    return {
        "last_started_at": _format_datetime(state.last_started_at),
        "last_finished_at": _format_datetime(state.last_finished_at),
        "last_status": state.last_status,
        "last_message": state.last_message,
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
