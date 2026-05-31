"""data 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def data(ctx: click.Context) -> None:
    """本地数据查询."""
    pass


@data.command()
@click.option(
    "--date",
    "-d",
    "date_str",
    default="today",
    help="日期: today / yesterday / 2026-05-23",
)
@click.pass_context
def stats(ctx: click.Context, date_str: str) -> None:
    """查看数据统计."""
    from stock_news.commands.data import stats as _stats

    _stats(date_str, ctx.obj["json_output"])


@data.command("list")
@click.option(
    "--date",
    "-d",
    "date_str",
    default="today",
    help="日期: today / yesterday / 2026-05-23",
)
@click.option("--source", "-s", help="筛选数据源: 个人消息 / 个人群")
@click.pass_context
def data_list(ctx: click.Context, date_str: str, source: str | None) -> None:
    """列出消息."""
    from stock_news.commands.data import list_messages

    list_messages(date_str, source, ctx.obj["json_output"])


@data.command()
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--dry-run", is_flag=True, help="只预览，不执行")
@click.pass_context
def dedup(ctx: click.Context, date_str: str, dry_run: bool) -> None:
    """去重消息."""
    from stock_news.commands.data import dedup as _dedup

    _dedup(date_str, dry_run, ctx.obj["json_output"])
