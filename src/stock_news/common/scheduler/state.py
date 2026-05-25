"""scheduler state.json 读写."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class JobState(BaseModel):
    enabled: bool = True
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_status: str | None = None
    last_duration_ms: int | None = None
    last_exit_code: int | None = None
    consecutive_failures: int = 0
    total_runs: int = 0
    total_failures: int = 0


def read_state(path: Path) -> dict[str, JobState]:
    if not path.exists():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, JobState] = {}
    for job_id, item in raw.items():
        if not isinstance(job_id, str) or not isinstance(item, dict):
            continue
        try:
            result[job_id] = JobState.model_validate(item)
        except Exception:
            continue
    return result


def write_state(path: Path, state: dict[str, JobState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v.model_dump(mode="json") for k, v in sorted(state.items())}
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def set_enabled(path: Path, job_id: str, enabled: bool) -> JobState:
    state = read_state(path)
    job_state = state.get(job_id, JobState())
    job_state.enabled = enabled
    state[job_id] = job_state
    write_state(path, state)
    return job_state
