from __future__ import annotations

import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.common.scheduler.config import ScheduleFile, ScheduleJob
from stock_news.common.scheduler.engine import is_due, tick
from stock_news.common.scheduler.state import JobState, read_state, write_state


def _schedule(tmp_path: Path, jobs: list[ScheduleJob]) -> ScheduleFile:
    return ScheduleFile(
        log_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "state.json"),
        lock_dir=str(tmp_path / "locks"),
        jobs=jobs,
    )


def test_tick_runs_due_every_job(tmp_path: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -c \"print('ok')\""
    schedule = _schedule(
        tmp_path,
        [ScheduleJob(id="ok", command=command, every="10m")],
    )

    summary = tick(schedule, now=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc))

    assert summary.due_count == 1
    assert summary.ran_count == 1
    assert summary.results[0].status == "success"
    state = read_state(schedule.state_path)
    assert state["ok"].last_status == "success"
    assert state["ok"].total_runs == 1
    assert (schedule.log_path / "ok.log").exists()


def test_every_job_not_due_before_interval(tmp_path: Path) -> None:
    now = datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc)
    job = ScheduleJob(id="wait", command="echo wait", every="10m")
    job_state = JobState(last_finished_at=now - timedelta(minutes=5))

    due, reason = is_due(job, job_state, now)

    assert due is False
    assert reason == "not_due"


def test_disabled_job_is_skipped(tmp_path: Path) -> None:
    schedule = _schedule(
        tmp_path,
        [ScheduleJob(id="off", command="echo off", every="10m")],
    )
    write_state(schedule.state_path, {"off": JobState(enabled=False)})

    summary = tick(schedule, now=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc))

    assert summary.due_count == 0
    assert summary.ran_count == 0
    assert summary.skipped_count == 1
    state = read_state(schedule.state_path)
    assert state["off"].total_runs == 0


def test_weekdays_job_runs_on_configured_day(tmp_path: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -c \"print('ok')\""
    schedule = _schedule(
        tmp_path,
        [ScheduleJob(id="weekday", command=command, at="16:30", weekdays="1-5")],
    )

    summary = tick(schedule, now=datetime(2026, 5, 25, 16, 30, tzinfo=timezone.utc))

    assert summary.due_count == 1
    assert summary.ran_count == 1


def test_weekdays_job_skips_outside_configured_days(tmp_path: Path) -> None:
    schedule = _schedule(
        tmp_path,
        [ScheduleJob(id="weekday", command="echo ok", at="16:30", weekdays="mon-fri")],
    )

    summary = tick(schedule, now=datetime(2026, 5, 31, 16, 30, tzinfo=timezone.utc))

    assert summary.due_count == 0
    assert summary.skipped_count == 1
    assert summary.results == []


def test_schedule_command_is_registered_without_alias() -> None:
    result = CliRunner().invoke(main, ["schedule", "--help"])

    assert result.exit_code == 0
    assert "tick" in result.output

    result = CliRunner().invoke(main, ["--help"])
    assert "schedule" in result.output
    assert "  sched " not in result.output
