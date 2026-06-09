"""调度主流程：due 判定、加锁、执行、落日志和状态."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from stock_news.common.scheduler.config import (
    ScheduleFile,
    ScheduleJob,
    is_in_active_hours,
    is_in_weekdays,
    parse_clock,
    parse_duration,
)
from stock_news.common.scheduler.lock import FileLock, LockBusy
from stock_news.common.scheduler.runner import run_command
from stock_news.common.scheduler.state import JobState, read_state, write_state


@dataclass(frozen=True)
class JobRunSummary:
    job_id: str
    status: str
    reason: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class TickSummary:
    started_at: str
    finished_at: str
    due_count: int
    ran_count: int
    skipped_count: int
    results: list[JobRunSummary]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _now() -> datetime:
    return datetime.now().astimezone()


def _append_jsonl(path: Path, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _as_aware(value: datetime | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=now.tzinfo)
    return value


def is_due(job: ScheduleJob, job_state: JobState, now: datetime) -> tuple[bool, str]:
    if not job_state.enabled:
        return False, "disabled"
    if not is_in_weekdays(job.weekdays, now):
        return False, "outside_weekdays"
    if not is_in_active_hours(job.active_hours, now):
        return False, "outside_active_hours"

    last_finished_at = _as_aware(job_state.last_finished_at, now)
    if job.every:
        if last_finished_at is None:
            return True, "never_run"
        elapsed = (now - last_finished_at).total_seconds()
        if elapsed >= parse_duration(job.every):
            return True, "interval_elapsed"
        return False, "not_due"

    assert job.at is not None
    scheduled_at = datetime.combine(now.date(), parse_clock(job.at), tzinfo=now.tzinfo)
    if now < scheduled_at:
        return False, "not_due"
    if last_finished_at is not None and last_finished_at.date() >= now.date():
        return False, "already_ran_today"
    return True, "scheduled_time_elapsed"


def _due_job_priority(job: ScheduleJob, index: int) -> tuple[int, str, int]:
    if job.at is not None:
        return (0, job.at, index)
    return (1, "", index)


def run_job(
    schedule: ScheduleFile,
    job: ScheduleJob,
    *,
    now: datetime | None = None,
) -> JobRunSummary:
    current = now or _now()
    log_path = schedule.log_path / f"{job.id}.log"
    lock_path = schedule.lock_path / f"{job.id}.lock"

    try:
        with FileLock(lock_path):
            state = read_state(schedule.state_path)
            job_state = state.get(job.id, JobState())
            job_state.last_started_at = current
            job_state.last_status = "running"
            state[job.id] = job_state
            write_state(schedule.state_path, state)
            _append_jsonl(
                log_path,
                {"ts": current.isoformat(), "status": "started"},
            )

            timeout = parse_duration(job.timeout) if job.timeout else None
            result = run_command(job.command, timeout)
            finished_at = _now()
            status = "success" if result.exit_code == 0 else "failure"
            reason = "timeout" if result.timed_out else None

            state = read_state(schedule.state_path)
            job_state = state.get(job.id, JobState())
            job_state.last_finished_at = finished_at
            job_state.last_status = status
            job_state.last_duration_ms = result.duration_ms
            job_state.last_exit_code = result.exit_code
            job_state.total_runs += 1
            if status == "success":
                job_state.consecutive_failures = 0
            else:
                job_state.total_failures += 1
                job_state.consecutive_failures += 1
            state[job.id] = job_state
            write_state(schedule.state_path, state)

            event: dict[str, object] = {
                "ts": finished_at.isoformat(),
                "status": status,
                "duration_ms": result.duration_ms,
                "exit_code": result.exit_code,
            }
            if reason:
                event["reason"] = reason
            if result.stdout_tail:
                event["stdout_tail"] = result.stdout_tail
            if result.stderr_tail:
                event["stderr_tail"] = result.stderr_tail
            _append_jsonl(log_path, event)

            return JobRunSummary(
                job_id=job.id,
                status=status,
                reason=reason,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
    except LockBusy:
        _append_jsonl(
            log_path,
            {
                "ts": current.isoformat(),
                "status": "skipped",
                "reason": "still_running",
            },
        )
        return JobRunSummary(job_id=job.id, status="skipped", reason="still_running")


def tick(schedule: ScheduleFile, *, now: datetime | None = None) -> TickSummary:
    started_at = now or _now()
    state = read_state(schedule.state_path)
    due_jobs: list[tuple[int, ScheduleJob]] = []
    skipped = 0

    for index, job in enumerate(schedule.jobs):
        job_state = state.get(job.id, JobState())
        due, reason = is_due(job, job_state, started_at)
        if due:
            due_jobs.append((index, job))
        else:
            skipped += 1
            _append_jsonl(
                schedule.tick_log_path,
                {
                    "ts": started_at.isoformat(),
                    "job_id": job.id,
                    "status": "skipped",
                    "reason": reason,
                },
            )

    due_jobs.sort(key=lambda item: _due_job_priority(item[1], item[0]))
    results = [run_job(schedule, job) for _, job in due_jobs]
    finished_at = _now()
    summary = TickSummary(
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        due_count=len(due_jobs),
        ran_count=sum(1 for item in results if item.status != "skipped"),
        skipped_count=skipped + sum(1 for item in results if item.status == "skipped"),
        results=results,
    )
    _append_jsonl(
        schedule.tick_log_path,
        {"ts": finished_at.isoformat(), "status": "tick_done", **summary.to_dict()},
    )
    return summary


def read_last_log_event(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    last_line = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    if last_line is None:
        return None
    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
