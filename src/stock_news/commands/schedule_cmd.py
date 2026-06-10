"""定时调度命令."""

from __future__ import annotations

import json
from pathlib import Path

import click

from stock_news.common.scheduler import launchd
from stock_news.common.scheduler.config import (
    SCHEDULE_CONFIG_FILE,
    ScheduleFile,
    ScheduleJob,
    load_schedule,
)
from stock_news.common.scheduler.engine import run_job, tick
from stock_news.common.scheduler.logging import read_last_log_event
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


@schedule.command("install")
@click.pass_context
def install_cmd(ctx: click.Context) -> None:
    """写入并加载 macOS launchd plist."""
    schedule_cfg = _load(create_if_missing=True)
    plist_path = launchd.install(schedule_cfg)
    if ctx.obj["json_output"]:
        _echo_json(
            {
                "ok": True,
                "plist": str(plist_path),
                "config": str(SCHEDULE_CONFIG_FILE),
                "message": "schedule 已安装",
            }
        )
    else:
        click.echo(f"schedule 已安装: {plist_path}")
        click.echo(f"配置文件: {SCHEDULE_CONFIG_FILE}")


@schedule.command("uninstall")
@click.pass_context
def uninstall_cmd(ctx: click.Context) -> None:
    """卸载 macOS launchd plist."""
    existed = launchd.uninstall()
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "removed": existed, "message": "schedule 已卸载"})
    else:
        click.echo("schedule 已卸载" if existed else "未发现已安装的 schedule plist")


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
    state = read_state(schedule_cfg.state_path)
    last_tick = read_last_log_event(schedule_cfg.tick_log_path)
    payload: dict[str, object] = {
        "loaded": launchd.is_loaded(),
        "plist": str(launchd.PLIST_PATH),
        "config": str(SCHEDULE_CONFIG_FILE),
        "jobs": len(schedule_cfg.jobs),
        "enabled_jobs": sum(
            1
            for job in schedule_cfg.jobs
            if state.get(job.id, None) is None or state[job.id].enabled
        ),
        "last_tick": last_tick,
    }
    if ctx.obj["json_output"]:
        _echo_json({"ok": True, "data": payload})
    else:
        click.echo(f"launchd: {'loaded' if payload['loaded'] else 'not loaded'}")
        click.echo(f"plist: {payload['plist']}")
        click.echo(f"config: {payload['config']}")
        click.echo(f"jobs: {payload['enabled_jobs']}/{payload['jobs']} enabled")
        if last_tick:
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
