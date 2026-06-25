"""项目内定时任务命令注册。

这里只提供进程内常驻循环和手动触发，不接系统 cron、launchd 或外部服务。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from datetime import datetime

import click

from stock_news.core.config import CONFIG_FILE, load
from stock_news.core.scheduler import (
    ScheduleStateStore,
    parse_duration,
    scheduler_server_status,
    start_scheduler_server,
    stop_scheduler_server,
)
from stock_news.usecases.configs.paths import ConfigPaths
from stock_news.usecases.scheduler import (
    build_schedule_status,
    run_due_tasks,
    run_scheduled_task,
)
from stock_news.usecases.scheduler.service import (
    TASK_CATALYST_STOCK_EXCEL,
    TASK_TUSHARE_SYNC,
    TASK_WECHAT_FETCH,
    TaskId,
)


@click.group()
@click.pass_context
def schedule(ctx: click.Context) -> None:
    """项目进程内定时任务."""


@schedule.command()
@click.option("--once", is_flag=True, help="只执行一次 tick 后退出")
@click.pass_context
def serve(ctx: click.Context, once: bool) -> None:
    """启动项目进程内定时循环。"""

    click.echo("定时任务进程已启动")
    while True:
        cfg = load()
        now = _now()
        store = _state_store()
        runs = run_due_tasks(cfg, store, now=now)
        for item in runs:
            _echo_run(item.task_id, item.ok, item.message)
        if once:
            return
        time.sleep(parse_duration(cfg.schedule.tick_interval).total_seconds())


@schedule.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """后台启动定时任务进程。"""

    status_data = start_scheduler_server(
        pid_file=_pid_path(),
        log_file=_log_path(),
        command=_serve_command(),
    )
    if ctx.obj["json_output"]:
        click.echo(json.dumps(asdict(status_data), ensure_ascii=False, indent=2))
        return
    if status_data.running:
        click.echo(f"后台进程: {status_data.message}")
        click.echo(f"PID: {status_data.pid}")
        click.echo(f"日志: {status_data.log_file}")
    else:
        raise click.ClickException(status_data.message)


@schedule.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """停止后台定时任务进程。"""

    status_data = stop_scheduler_server(pid_file=_pid_path(), log_file=_log_path())
    if ctx.obj["json_output"]:
        click.echo(json.dumps(asdict(status_data), ensure_ascii=False, indent=2))
        return
    click.echo(f"后台进程: {status_data.message}")
    if status_data.pid:
        click.echo(f"PID: {status_data.pid}")


@schedule.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """重启后台定时任务进程。"""

    stop_scheduler_server(pid_file=_pid_path(), log_file=_log_path())
    status_data = start_scheduler_server(
        pid_file=_pid_path(),
        log_file=_log_path(),
        command=_serve_command(),
    )
    if ctx.obj["json_output"]:
        click.echo(json.dumps(asdict(status_data), ensure_ascii=False, indent=2))
        return
    if not status_data.running:
        raise click.ClickException(status_data.message)
    click.echo("后台进程: 已重启")
    click.echo(f"PID: {status_data.pid}")
    click.echo(f"日志: {status_data.log_file}")


@schedule.command("run")
@click.argument(
    "task",
    type=click.Choice(
        ["wechat", "market", "tushare", "catalyst-excel", "strategy", "all"]
    ),
)
@click.pass_context
def run_command(ctx: click.Context, task: str) -> None:
    """手动执行一次固定任务。"""

    cfg = load()
    store = _state_store()
    now = _now()
    task_ids = _resolve_task_ids(task)
    runs = [run_scheduled_task(cfg, store, task_id, now=now) for task_id in task_ids]
    if ctx.obj["json_output"]:
        click.echo(
            json.dumps(
                [asdict(item) for item in runs],
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )
        return
    for item in runs:
        _echo_run(item.task_id, item.ok, item.message)
    failed = [item for item in runs if not item.ok]
    if failed:
        raise click.ClickException(f"失败任务: {len(failed)}")


@schedule.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """查看定时任务状态。"""

    cfg = load()
    store = _state_store()
    rows = build_schedule_status(cfg, store, now=_now())
    server = scheduler_server_status(pid_file=_pid_path(), log_file=_log_path())
    if ctx.obj["json_output"]:
        click.echo(
            json.dumps(
                {
                    "server": asdict(server),
                    "tasks": [asdict(item) for item in rows],
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )
        return

    click.echo(f"后台进程: {server.message}")
    click.echo(f"PID: {server.pid or '-'}")
    click.echo(f"PID 文件: {server.pid_file}")
    click.echo(f"日志文件: {server.log_file}")
    click.echo("")
    click.echo(f"状态文件: {_state_path()}")
    click.echo(f"调度开关: {'启用' if cfg.schedule.enabled else '停用'}")
    click.echo(f"tick_interval: {cfg.schedule.tick_interval}")
    for item in rows:
        click.echo("")
        click.echo(f"{item.task_id}: {'启用' if item.enabled else '停用'}")
        click.echo(f"  触发: {item.trigger}")
        click.echo(f"  到期: {'是' if item.due else '否'}")
        click.echo(f"  最近状态: {item.last_status or '-'}")
        click.echo(f"  最近开始: {item.last_started_at or '-'}")
        click.echo(f"  最近结束: {item.last_finished_at or '-'}")
        if item.last_message:
            click.echo(f"  最近结果: {item.last_message}")


def _state_store() -> ScheduleStateStore:
    return ScheduleStateStore(_state_path())


def _state_path() -> str:
    paths = ConfigPaths.from_legacy_file(CONFIG_FILE)
    return str(paths.schedule_state_file)


def _pid_path() -> str:
    paths = ConfigPaths.from_legacy_file(CONFIG_FILE)
    return str(paths.schedule_pid_file)


def _log_path() -> str:
    paths = ConfigPaths.from_legacy_file(CONFIG_FILE)
    return str(paths.schedule_log_file)


def _serve_command() -> list[str]:
    return [sys.executable, "-m", "stock_news", "schedule", "serve"]


def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _resolve_task_ids(task: str) -> list[TaskId]:
    task_map: dict[str, list[TaskId]] = {
        "wechat": [TASK_WECHAT_FETCH],
        "market": [TASK_TUSHARE_SYNC],
        "tushare": [TASK_TUSHARE_SYNC],
        "catalyst-excel": [TASK_CATALYST_STOCK_EXCEL],
        "strategy": [TASK_CATALYST_STOCK_EXCEL],
        "all": [TASK_WECHAT_FETCH, TASK_TUSHARE_SYNC, TASK_CATALYST_STOCK_EXCEL],
    }
    return task_map[task]


def _echo_run(task_id: TaskId, ok: bool, msg: str) -> None:
    color = "green" if ok else "red"
    status = "成功" if ok else "失败"
    click.secho(f"{task_id}: {status} {msg}", fg=color)
