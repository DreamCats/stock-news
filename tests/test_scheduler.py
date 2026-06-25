from __future__ import annotations

import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import schedule_cmd
from stock_news.common.scheduler.config import ScheduleFile, ScheduleJob
from stock_news.common.scheduler.engine import is_due, tick
from stock_news.common.scheduler.lock import FileLock
from stock_news.common.scheduler.logging import append_jsonl
from stock_news.common.scheduler.service import (
    SchedulerAlreadyRunning,
    is_scheduler_running,
    run_scheduler_loop,
    scheduler_lock_path,
    scheduler_pid_path,
    scheduler_status,
    start_scheduler_process,
    stop_scheduler_process,
    write_scheduler_pid,
)
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


def test_tick_prioritizes_at_jobs_over_every_jobs(tmp_path: Path) -> None:
    order_path = tmp_path / "order.txt"

    def append_cmd(name: str) -> str:
        script = (
            "from pathlib import Path; "
            f"Path({str(order_path)!r}).open('a').write({name + chr(10)!r})"
        )
        return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"

    schedule = _schedule(
        tmp_path,
        [
            ScheduleJob(id="workflow", command=append_cmd("workflow"), every="30m"),
            ScheduleJob(id="nightly", command=append_cmd("nightly"), at="21:00"),
        ],
    )

    summary = tick(schedule, now=datetime(2026, 6, 9, 21, 3, tzinfo=timezone.utc))

    assert summary.due_count == 2
    assert [item.job_id for item in summary.results] == ["nightly", "workflow"]
    assert order_path.read_text(encoding="utf-8").splitlines() == [
        "nightly",
        "workflow",
    ]


def test_schedule_command_is_registered_without_alias() -> None:
    result = CliRunner().invoke(main, ["schedule", "--help"])

    assert result.exit_code == 0
    assert "restart" in result.output
    assert "serve" in result.output
    assert "start" in result.output
    assert "stop" in result.output
    assert "tick" in result.output
    assert "install" not in result.output
    assert "uninstall" not in result.output

    result = CliRunner().invoke(main, ["--help"])
    assert "schedule" in result.output
    assert "  sched " not in result.output


def test_schedule_tick_quiet_suppresses_stdout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(schedule_cmd, "_load", lambda: _schedule(tmp_path, []))

    result = CliRunner().invoke(main, ["schedule", "tick", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""


def test_project_scheduler_running_status_uses_process_lock(tmp_path: Path) -> None:
    schedule = _schedule(tmp_path, [])

    assert is_scheduler_running(schedule) is False
    with FileLock(scheduler_lock_path(schedule)):
        assert is_scheduler_running(schedule) is True


def test_project_scheduler_loop_ticks_until_stop(tmp_path: Path) -> None:
    schedule = _schedule(tmp_path, [])
    tick_count = 0

    def on_tick(_summary: object) -> None:
        nonlocal tick_count
        tick_count += 1

    run_scheduler_loop(
        load_fn=lambda: schedule,
        on_tick=on_tick,
        should_stop=lambda: tick_count >= 1,
        sleep_fn=lambda _seconds: None,
    )

    assert tick_count == 1
    assert schedule.tick_log_path.exists()


def test_project_scheduler_loop_rejects_duplicate_process(tmp_path: Path) -> None:
    schedule = _schedule(tmp_path, [])

    with FileLock(scheduler_lock_path(schedule)):
        with pytest.raises(SchedulerAlreadyRunning):
            run_scheduler_loop(
                load_fn=lambda: schedule,
                should_stop=lambda: True,
                sleep_fn=lambda _seconds: None,
            )


def test_project_scheduler_start_stop_manages_background_process(
    tmp_path: Path,
) -> None:
    schedule = _schedule(tmp_path, [])
    lock_path = scheduler_lock_path(schedule)
    fake_sn = tmp_path / "fake-sn"
    script = (
        "#!/bin/sh\n"
        "exec "
        f"{shlex.quote(sys.executable)}"
        " -c "
        + shlex.quote(
            "import fcntl, time; "
            f"f=open({str(lock_path)!r}, 'a+'); "
            "fcntl.flock(f.fileno(), fcntl.LOCK_EX); "
            "time.sleep(60)"
        )
        + "\n"
    )
    fake_sn.write_text(script, encoding="utf-8")
    fake_sn.chmod(0o755)

    status = start_scheduler_process(
        schedule,
        sn_executable=str(fake_sn),
        startup_wait_seconds=2,
    )

    assert status.running is True
    assert status.pid is not None
    assert scheduler_pid_path(schedule).exists()

    stopped = stop_scheduler_process(schedule, timeout_seconds=2)

    assert stopped.running is False
    assert not scheduler_pid_path(schedule).exists()


def test_project_scheduler_stop_clears_stale_pid(tmp_path: Path) -> None:
    schedule = _schedule(tmp_path, [])
    write_scheduler_pid(schedule, 99999999)

    status = scheduler_status(schedule)
    assert status.stale_pid is True

    stopped = stop_scheduler_process(schedule)

    assert stopped.running is False
    assert not scheduler_pid_path(schedule).exists()


def test_schedule_log_rotates_when_size_limit_is_reached(tmp_path: Path) -> None:
    log_path = tmp_path / "tick.log"
    log_path.write_text("x" * 20, encoding="utf-8")

    append_jsonl(
        log_path,
        {"ts": "2026-06-10T21:00:00+08:00", "status": "ok"},
        max_bytes=10,
    )

    assert (tmp_path / "tick.log.1").read_text(encoding="utf-8") == "x" * 20
    assert '"status": "ok"' in log_path.read_text(encoding="utf-8")
