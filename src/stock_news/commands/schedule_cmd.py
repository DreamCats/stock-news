"""定时调度命令."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from types import FrameType

import click

from stock_news.common.scheduler.config import (
    SCHEDULE_CONFIG_FILE,
    ScheduleFile,
    ScheduleJob,
    load_schedule,
)
from stock_news.common.scheduler.engine import TickSummary, run_job, tick
from stock_news.common.scheduler.logging import read_last_log_event
from stock_news.common.scheduler.service import (
    SchedulerAlreadyRunning,
    SchedulerStatus,
    SchedulerStopTimeout,
    clear_scheduler_pid,
    run_scheduler_loop,
    scheduler_lock_path,
    scheduler_pid_path,
    scheduler_status,
    scheduler_stderr_path,
    scheduler_stdout_path,
    start_scheduler_process,
    stop_scheduler_process,
)
from stock_news.common.scheduler.state import read_state, set_enabled


def _echo_json(payload: dict[str, object]) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _load(*, create_if_missing: bool = False) -> ScheduleFile:
    return load_schedule(create_if_missing=create_if_missing)


def _find_job(schedule: ScheduleFile, job_id: str) -> ScheduleJob:
    for job in schedule.jobs:
        if job.id == job_id:
            return job
    raise click.ClickException(f"未找到 schedule job: {job_id}")


def _tail_lines(path: Path, count: int) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[-count:]


@click.group(name="schedule")
def schedule() -> None:
    """本地定时调度."""


def _status_payload(schedule_cfg: ScheduleFile) -> dict[str, object]:
    state = read_state(schedule_cfg.state_path)
    last_tick = read_last_log_event(schedule_cfg.tick_log_path)
    status = scheduler_status(schedule_cfg)
    return {
        "mode": "project",
        "running": status.running,
        "pid": status.pid,
        "pid_running": status.pid_running,
        "stale_pid": status.stale_pid,
        "pid_file": str(scheduler_pid_path(schedule_cfg)),
        "lock": str(scheduler_lock_path(schedule_cfg)),
        "stdout_log": str(scheduler_stdout_path(schedule_cfg)),
        "stderr_log": str(scheduler_stderr_path(schedule_cfg)),
        "config": str(SCHEDULE_CONFIG_FILE),
        "tick_interval": schedule_cfg.tick_interval,
        "jobs": len(schedule_cfg.jobs),
        "enabled_jobs": sum(
            1
            for job in schedule_cfg.jobs
            if state.get(job.id, None) is None or state[job.id].enabled
        ),
        "last_tick": last_tick,
    }


def _echo_process_status(action: str, status: SchedulerStatus) -> None:
    suffix = f": pid={status.pid}" if status.pid is not None else ""
    click.echo(f"project scheduler {action}{suffix}")


@schedule.command("start")
@click.pass_context
def start_cmd(ctx: click.Context) -> None:
    """后台启动项目级 scheduler."""
    schedule_cfg = _load(create_if_missing=True)
    before = scheduler_status(schedule_cfg)
    status = start_scheduler_process(schedule_cfg)
    payload = _status_payload(schedule_cfg)
    payload["already_running"] = before.running
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "data": payload})
        return
    if before.running:
        _echo_process_status("已在运行", status)
    else:
        _echo_process_status("已后台启动", status)
    click.echo(f"stdout: {payload['stdout_log']}")
    click.echo(f"stderr: {payload['stderr_log']}")


@schedule.command("stop")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="等待秒数")
@click.option("--force", is_flag=True, help="超时后强制结束 scheduler 进程组")
@click.pass_context
def stop_cmd(ctx: click.Context, timeout: float, force: bool) -> None:
    """停止后台项目级 scheduler."""
    schedule_cfg = _load()
    before = scheduler_status(schedule_cfg)
    try:
        status = stop_scheduler_process(
            schedule_cfg,
            timeout_seconds=timeout,
            force=force,
        )
    except SchedulerStopTimeout as exc:
        raise click.ClickException(
            f"project scheduler 停止超时: pid={exc}; 如确认要中断当前任务，可加 --force"
        ) from exc
    payload = _status_payload(schedule_cfg)
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "data": payload})
        return
    if before.stale_pid:
        click.echo("已清理 stale scheduler pid")
    elif before.running and not status.running:
        _echo_process_status("已停止", before)
    elif status.running:
        click.echo("project scheduler 仍在运行；如果是前台 serve，请在原终端停止")
    else:
        click.echo("project scheduler 未运行")


@schedule.command("restart")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="等待秒数")
@click.option("--force", is_flag=True, help="超时后强制结束 scheduler 进程组")
@click.pass_context
def restart_cmd(ctx: click.Context, timeout: float, force: bool) -> None:
    """重启后台项目级 scheduler."""
    schedule_cfg = _load(create_if_missing=True)
    try:
        stopped = stop_scheduler_process(
            schedule_cfg,
            timeout_seconds=timeout,
            force=force,
        )
    except SchedulerStopTimeout as exc:
        raise click.ClickException(
            f"project scheduler 停止超时: pid={exc}; 如确认要中断当前任务，可加 --force"
        ) from exc
    if stopped.running:
        raise click.ClickException("project scheduler 仍在运行，无法 restart")
    started = start_scheduler_process(schedule_cfg)
    payload = _status_payload(schedule_cfg)
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "data": payload})
        return
    _echo_process_status("已重启", started)
    click.echo(f"stdout: {payload['stdout_log']}")
    click.echo(f"stderr: {payload['stderr_log']}")


@schedule.command("serve")
@click.option("--quiet", is_flag=True, help="只写调度日志，不向 stdout 输出 tick 摘要")
@click.pass_context
def serve_cmd(ctx: click.Context, quiet: bool) -> None:
    """在当前项目进程内持续执行 due job 检查."""
    stop_requested = False
    started = False

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def on_start(schedule_cfg: ScheduleFile, lock_path: Path) -> None:
        nonlocal started
        started = True
        if quiet:
            return
        if ctx.obj["json_output"]:
            _echo_json(
                {
                    "ok": True,
                    "event": "started",
                    "mode": "project",
                    "tick_interval": schedule_cfg.tick_interval,
                    "lock": str(lock_path),
                    "config": str(SCHEDULE_CONFIG_FILE),
                }
            )
            return
        click.echo(
            "project scheduler 已启动: "
            f"tick_interval={schedule_cfg.tick_interval}, lock={lock_path}"
        )

    def on_tick_summary(summary: TickSummary) -> None:
        if quiet:
            return
        if ctx.obj["json_output"]:
            _echo_json({"ok": True, "event": "tick", "data": summary.to_dict()})
            return
        click.echo(
            "tick 完成: "
            f"due={summary.due_count}, ran={summary.ran_count}, "
            f"skipped={summary.skipped_count}"
        )

    try:
        run_scheduler_loop(
            on_start=on_start,
            on_tick=on_tick_summary,
            should_stop=lambda: stop_requested,
        )
    except SchedulerAlreadyRunning as exc:
        raise click.ClickException(f"project scheduler 已在运行: {exc}") from exc
    finally:
        try:
            clear_scheduler_pid(_load(), expected_pid=os.getpid())
        except Exception:
            pass
        if started and not quiet and not ctx.obj["json_output"]:
            click.echo("project scheduler 已停止")


@schedule.command("tick")
@click.option("--quiet", is_flag=True, help="只写调度日志，不向 stdout 输出摘要")
@click.pass_context
def tick_cmd(ctx: click.Context, quiet: bool) -> None:
    """执行一轮 due job 检查."""
    summary = tick(_load())
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "data": summary.to_dict()})
    elif quiet:
        return
    else:
        click.echo(
            "tick 完成: "
            f"due={summary.due_count}, ran={summary.ran_count}, "
            f"skipped={summary.skipped_count}"
        )
        for item in summary.results:
            suffix = f", exit={item.exit_code}" if item.exit_code is not None else ""
            click.echo(f"  {item.job_id}: {item.status}{suffix}")


@schedule.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """列出 schedule jobs."""
    schedule_cfg = _load()
    state = read_state(schedule_cfg.state_path)
    jobs: list[dict[str, object]] = []
    for job in schedule_cfg.jobs:
        job_state = state.get(job.id)
        jobs.append(
            {
                "id": job.id,
                "command": job.command,
                "every": job.every,
                "at": job.at,
                "weekdays": job.weekdays,
                "active_hours": job.active_hours,
                "timeout": job.timeout,
                "enabled": True if job_state is None else job_state.enabled,
                "last_status": None if job_state is None else job_state.last_status,
                "last_finished_at": None
                if job_state is None or job_state.last_finished_at is None
                else job_state.last_finished_at.isoformat(),
                "total_runs": 0 if job_state is None else job_state.total_runs,
                "consecutive_failures": 0
                if job_state is None
                else job_state.consecutive_failures,
            }
        )

    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "jobs": jobs})
        return

    if not jobs:
        click.echo(f"未配置 schedule job，可编辑 {SCHEDULE_CONFIG_FILE}")
        return
    for item in jobs:
        cadence = item["every"] or f"at {item['at']}"
        if item["weekdays"]:
            cadence = f"{cadence} weekdays={item['weekdays']}"
        enabled = "enabled" if item["enabled"] else "disabled"
        click.echo(
            f"{item['id']} [{enabled}] {cadence} "
            f"last={item['last_status'] or '-'} runs={item['total_runs']}"
        )
        click.echo(f"  {item['command']}")


@schedule.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """查看 scheduler 状态."""
    schedule_cfg = _load()
    payload = _status_payload(schedule_cfg)
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "data": payload})
    else:
        running = bool(payload["running"])
        click.echo(f"project scheduler: {'running' if running else 'not running'}")
        click.echo(f"pid: {payload['pid'] or '-'}")
        click.echo(f"pid_file: {payload['pid_file']}")
        click.echo(f"lock: {payload['lock']}")
        click.echo(f"stdout: {payload['stdout_log']}")
        click.echo(f"stderr: {payload['stderr_log']}")
        click.echo(f"config: {payload['config']}")
        click.echo(f"tick_interval: {payload['tick_interval']}")
        click.echo(f"jobs: {payload['enabled_jobs']}/{payload['jobs']} enabled")
        if payload["stale_pid"]:
            click.echo("stale_pid: yes")
        last_tick = payload["last_tick"]
        if isinstance(last_tick, dict):
            click.echo(
                f"last tick: {last_tick.get('finished_at') or last_tick.get('ts')}"
            )


@schedule.command("run")
@click.argument("job_id")
@click.pass_context
def run_cmd(ctx: click.Context, job_id: str) -> None:
    """手动强跑某个 job."""
    schedule_cfg = _load()
    summary = run_job(schedule_cfg, _find_job(schedule_cfg, job_id))
    if ctx.obj["json_output"]:
        _echo_json({"ok": summary.status == "success", "data": summary.__dict__})
    else:
        click.echo(f"{summary.job_id}: {summary.status}")
        if summary.exit_code is not None:
            click.echo(f"exit_code: {summary.exit_code}")


@schedule.command("logs")
@click.option("--job", "job_id", help="指定 job id；不传则查看 tick 日志")
@click.option("--tail", type=int, default=20, show_default=True, help="显示最后 N 行")
@click.pass_context
def logs_cmd(ctx: click.Context, job_id: str | None, tail: int) -> None:
    """查看 schedule 日志."""
    schedule_cfg = _load()
    path = (
        schedule_cfg.log_path / f"{job_id}.log"
        if job_id
        else schedule_cfg.tick_log_path
    )
    lines = _tail_lines(path, tail)
    if ctx.obj["json_output"]:
        events: list[object] = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append(line)
        _echo_json({"ok": True, "path": str(path), "events": events})
        return
    if not lines:
        click.echo(f"无日志: {path}")
        return
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            click.echo(line)
            continue
        ts = event.get("ts", "-")
        status = event.get("status", "-")
        reason = event.get("reason")
        job = event.get("job_id")
        prefix = f"{ts} {job} {status}" if job else f"{ts} {status}"
        click.echo(f"{prefix} ({reason})" if reason else prefix)


@schedule.command("enable")
@click.argument("job_id")
@click.pass_context
def enable_cmd(ctx: click.Context, job_id: str) -> None:
    """启用某个 job."""
    schedule_cfg = _load()
    _find_job(schedule_cfg, job_id)
    job_state = set_enabled(schedule_cfg.state_path, job_id, True)
    if ctx.obj["json_output"]:
        _echo_json(
            {"ok": True, "job_id": job_id, "state": job_state.model_dump(mode="json")}
        )
    else:
        click.echo(f"已启用: {job_id}")


@schedule.command("disable")
@click.argument("job_id")
@click.pass_context
def disable_cmd(ctx: click.Context, job_id: str) -> None:
    """禁用某个 job."""
    schedule_cfg = _load()
    _find_job(schedule_cfg, job_id)
    job_state = set_enabled(schedule_cfg.state_path, job_id, False)
    if ctx.obj["json_output"]:
        _echo_json(
            {"ok": True, "job_id": job_id, "state": job_state.model_dump(mode="json")}
        )
    else:
        click.echo(f"已禁用: {job_id}")
