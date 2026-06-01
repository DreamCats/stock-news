"""source 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def source(ctx: click.Context) -> None:
    """源头雷达：扫描新概念、催化和扩散线索."""
    pass


@source.command("extract")
@click.option(
    "--date",
    "date_str",
    default="today",
    show_default=True,
    help="日期: 2026-05-13 / today / yesterday",
)
@click.option(
    "--min-confidence",
    type=click.FloatRange(min=0.0, max=1.0),
    default=0.7,
    show_default=True,
    help="进入源头抽取的 classify 最低置信度",
)
@click.pass_context
def extract(
    ctx: click.Context,
    date_str: str,
    min_confidence: float,
) -> None:
    """从 research 分类消息抽取源头候选."""
    from stock_news.commands.source_extract import extract_source_candidates

    extract_source_candidates(
        date_str=date_str,
        min_confidence=min_confidence,
        json_output=ctx.obj["json_output"],
    )


@source.command("scan")
@click.option(
    "--since-minutes",
    type=click.IntRange(min=1),
    help="只扫描最近 N 分钟的新消息",
)
@click.option(
    "--start",
    "start_str",
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
    "--lookback-days",
    type=click.IntRange(min=0),
    default=30,
    show_default=True,
    help="向前回看多少天的全量语料，用于判定“全新/历史提及”",
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
@click.option(
    "--markdown",
    "write_markdown",
    is_flag=True,
    help="把榜单渲染成 Markdown 落盘到 data/<end>/source_scan/radar.md",
)
@click.option(
    "--markdown-out",
    "markdown_out",
    help="自定义 Markdown 输出路径（指定即落盘，覆盖默认路径）",
)
@click.pass_context
def scan(
    ctx: click.Context,
    since_minutes: int | None,
    start_str: str | None,
    end_str: str,
    lookahead_days: int,
    lookback_days: int,
    top: int,
    max_message_chars: int,
    write_markdown: bool,
    markdown_out: str | None,
) -> None:
    """扫描源头候选."""
    from stock_news.commands.source import scan_sources

    scan_sources(
        since_minutes=since_minutes,
        start_str=start_str,
        end_str=end_str,
        lookahead_days=lookahead_days,
        lookback_days=lookback_days,
        top=top,
        max_message_chars=max_message_chars,
        json_output=ctx.obj["json_output"],
        write_markdown=write_markdown,
        markdown_out=markdown_out,
    )
