"""微信数据源命令注册。

这里只接线微信原始消息拉取，不做分析和投递。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import click

from stock_news.core.config import load
from stock_news.core.wechat import TimeWindow
from stock_news.usecases.wechat_fetch import fetch_wechat_messages

TIME_FMT = "%Y%m%d%H%M%S"


@click.group()
@click.pass_context
def wechat(ctx: click.Context) -> None:
    """微信数据源."""


@wechat.command()
@click.option("--source", "-s", default="all", help="数据源: 个人消息 / 个人群 / all")
@click.option("--last", help="拉取最近 N 分钟/小时，如 30m / 2h")
@click.option("--start", help="开始时间，格式 yyyyMMddHHmmss")
@click.option("--end", help="结束时间，格式 yyyyMMddHHmmss")
@click.option("--refresh", is_flag=True, help="忽略增量窗口状态，强制重拉")
@click.pass_context
def fetch(
    ctx: click.Context,
    source: str,
    last: str | None,
    start: str | None,
    end: str | None,
    refresh: bool,
) -> None:
    """拉取微信原始消息并写入 SQLite。"""

    cfg = load()
    now = datetime.now().astimezone().replace(microsecond=0)
    window = _resolve_window(last=last, start=start, end=end, now=now)
    sources = cfg.wechat.sources if source == "all" else [source]
    summary = fetch_wechat_messages(
        config=cfg.wechat,
        sources=sources,
        windows=[window],
        now=now,
        refresh=refresh,
    )
    if ctx.obj["json_output"]:
        click.echo(
            json.dumps(
                {
                    "ok": not summary.errors,
                    "planned": summary.planned,
                    "skipped": summary.skipped,
                    "fetched": summary.fetched,
                    "inserted": summary.inserted,
                    "duplicated": summary.duplicated,
                    "errors": [item.__dict__ for item in summary.errors],
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )
        return

    start_text = window.start.strftime(TIME_FMT)
    end_text = window.end.strftime(TIME_FMT)
    click.echo(f"窗口: {start_text} - {end_text}")
    click.echo(f"数据源: {', '.join(sources)}")
    click.echo(f"计划切片: {summary.planned}，跳过切片: {summary.skipped}")
    click.echo(f"拉取消息: {summary.fetched}，新增: {summary.inserted}")
    click.echo(f"重复消息: {summary.duplicated}")
    if summary.errors:
        click.secho(f"失败切片: {len(summary.errors)}", fg="yellow", err=True)
        for error in summary.errors[:5]:
            click.secho(
                f"  [{error.source}] {error.start.strftime(TIME_FMT)}-"
                f"{error.end.strftime(TIME_FMT)}: {error.error}",
                fg="yellow",
                err=True,
            )
        raise click.ClickException("部分微信切片拉取失败")


def _resolve_window(
    *,
    last: str | None,
    start: str | None,
    end: str | None,
    now: datetime,
) -> TimeWindow:
    selected = sum(bool(item) for item in (last, start or end))
    if selected != 1:
        raise click.ClickException("需要且只能指定 --last 或 --start/--end")
    if last:
        return TimeWindow(start=_parse_last(last, now), end=now)
    if not start or not end:
        raise click.ClickException("--start 和 --end 必须同时指定")
    return TimeWindow(
        start=datetime.strptime(start, TIME_FMT).replace(tzinfo=now.tzinfo),
        end=datetime.strptime(end, TIME_FMT).replace(tzinfo=now.tzinfo),
    )


def _parse_last(last: str, now: datetime) -> datetime:
    match = re.match(r"^(\d+)([mh])$", last)
    if not match:
        raise click.ClickException("--last 格式错误，示例: 30m, 2h")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return now - timedelta(minutes=amount)
    return now - timedelta(hours=amount)
