"""fetch 命令注册."""

from __future__ import annotations

import click


@click.command()
@click.option(
    "--source",
    "-s",
    default="all",
    help="数据源: 个人消息 / 个人群 / all",
)
@click.option("--start", help="开始时间，格式 yyyyMMddHHmmss")
@click.option("--end", help="结束时间，格式 yyyyMMddHHmmss")
@click.option("--last", help="拉取最近 N 分钟/小时，如 30m / 2h")
@click.option("--date", "date_str", help="日期: today / yesterday / 2026-05-25")
@click.option("--time-range", help="日内时间范围，如 09:00-23:00")
@click.option(
    "--slice-hours",
    type=int,
    default=1,
    help="按 N 小时切片拉取，默认 1（窗口小于切片则不切）",
)
@click.option("--workers", type=int, default=4, help="并发请求数，默认 4")
@click.option(
    "--refresh",
    is_flag=True,
    help="忽略切片缓存，强制重拉所有切片",
)
@click.pass_context
def fetch(
    ctx: click.Context,
    source: str,
    start: str | None,
    end: str | None,
    last: str | None,
    date_str: str | None,
    time_range: str | None,
    slice_hours: int,
    workers: int,
    refresh: bool,
) -> None:
    """拉取微信 API 消息."""
    from stock_news.commands.fetch import run_fetch

    run_fetch(
        source,
        start,
        end,
        last,
        date_str,
        time_range,
        ctx.obj["json_output"],
        slice_hours,
        workers,
        refresh,
    )
