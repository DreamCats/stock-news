"""source 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def source(ctx: click.Context) -> None:
    """源头雷达：扫描新概念、催化和扩散线索."""
    pass


@source.command("scan")
@click.option(
    "--start",
    "start_str",
    required=True,
    help="开始日期: 2026-05-01 / today / yesterday",
)
@click.option(
    "--end",
    "end_str",
    default="today",
    show_default=True,
    help="结束日期: 2026-05-13 / today / yesterday",
)
@click.option(
    "--lookahead-days",
    type=click.IntRange(min=0),
    default=5,
    show_default=True,
    help="向后观察扩散和首次带股的天数",
)
@click.option(
    "--top",
    "-n",
    type=click.IntRange(min=1),
    default=30,
    help="显示前 N 个候选",
)
@click.option(
    "--max-message-chars",
    type=click.IntRange(min=20),
    default=300,
    show_default=True,
    help="源头候选消息最大长度",
)
@click.pass_context
def scan(
    ctx: click.Context,
    start_str: str,
    end_str: str,
    lookahead_days: int,
    top: int,
    max_message_chars: int,
) -> None:
    """扫描源头候选."""
    from stock_news.commands.source import scan_sources

    scan_sources(
        start_str=start_str,
        end_str=end_str,
        lookahead_days=lookahead_days,
        top=top,
        max_message_chars=max_message_chars,
        json_output=ctx.obj["json_output"],
    )
