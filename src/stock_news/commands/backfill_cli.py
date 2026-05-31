"""backfill 命令注册."""

from __future__ import annotations

import click


@click.command("backfill")
@click.option(
    "--days",
    type=click.IntRange(min=1),
    default=30,
    show_default=True,
    help="向前补齐最近 N 天",
)
@click.option("--end-date", default="today", show_default=True, help="结束日期")
@click.option(
    "--time-range",
    default="09:00-23:00",
    show_default=True,
    help="每日拉取时间窗口",
)
@click.option("--source", "-s", default="all", show_default=True, help="数据源")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.option(
    "--slice-hours", type=int, default=1, show_default=True, help="fetch 切片小时数"
)
@click.option("--workers", type=int, default=4, show_default=True, help="fetch 并发数")
@click.option("--dry-run", is_flag=True, help="只展示将补齐的日期和阶段")
@click.pass_context
def backfill(
    ctx: click.Context,
    days: int,
    end_date: str,
    time_range: str,
    source: str,
    provider: str | None,
    slice_hours: int,
    workers: int,
    dry_run: bool,
) -> None:
    """顺序补齐历史窗口数据."""
    from stock_news.commands.backfill import run_backfill

    run_backfill(
        days,
        end_date,
        time_range,
        source,
        provider,
        slice_hours,
        workers,
        dry_run,
        ctx.obj["json_output"],
    )
