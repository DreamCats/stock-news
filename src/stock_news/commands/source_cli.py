"""source 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def source(ctx: click.Context) -> None:
    """源头雷达：发现成熟锚点后的陌生新组合."""
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
    default=0.6,
    show_default=True,
    help="进入结构抽取的 classify 最低置信度",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    help="最多处理 N 条新消息，便于低频试运行控量",
)
@click.option(
    "--max-message-chars",
    type=click.IntRange(min=100),
    default=1800,
    show_default=True,
    help="送入结构抽取的消息最大长度",
)
@click.option(
    "--provider",
    "-p",
    help="指定单个 LLM provider；不指定则使用 source_extract provider pool",
)
@click.option(
    "--reset",
    is_flag=True,
    help="清空当日 structures.json 后重跑",
)
@click.pass_context
def extract(
    ctx: click.Context,
    date_str: str,
    min_confidence: float,
    limit: int | None,
    max_message_chars: int,
    provider: str | None,
    reset: bool,
) -> None:
    """阶段二：LLM 结构抽取，只产出可回指原文的 span."""
    from stock_news.commands.source_extract import extract_source_candidates

    extract_source_candidates(
        date_str=date_str,
        min_confidence=min_confidence,
        limit=limit,
        max_message_chars=max_message_chars,
        provider_name=provider,
        reset=reset,
        json_output=ctx.obj["json_output"],
    )


@source.command("scan")
@click.option(
    "--date",
    "date_str",
    default="today",
    show_default=True,
    help="扫描日期: 2026-05-13 / today / yesterday",
)
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
    help="结束日期: 2026-05-13 / today / yesterday",
)
@click.option(
    "--as-of",
    "as_of_str",
    help="证据截止时间: 09:20 / 2026-05-11T10:30:00 / now；默认自动",
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
    default=1500,
    show_default=True,
    help="源头候选消息最大长度",
)
@click.option(
    "--include-closed",
    is_flag=True,
    help="显示 old_theme/crowded 等已关闭状态",
)
@click.option(
    "--markdown",
    "write_markdown",
    is_flag=True,
    help="把老板版 Markdown 落盘到 data/<end>/source_scan/radar.md",
)
@click.option(
    "--markdown-out",
    "markdown_out",
    help="自定义老板版 Markdown 输出路径（指定即落盘，覆盖默认路径）",
)
@click.option(
    "--no-llm-brief",
    "use_llm_brief",
    is_flag=True,
    flag_value=False,
    default=True,
    help="Markdown 落盘时不调用 LLM，使用本地短版",
)
@click.pass_context
def scan(
    ctx: click.Context,
    date_str: str,
    since_minutes: int | None,
    start_str: str | None,
    end_str: str | None,
    as_of_str: str | None,
    lookback_days: int,
    top: int,
    max_message_chars: int,
    include_closed: bool,
    write_markdown: bool,
    markdown_out: str | None,
    use_llm_brief: bool,
) -> None:
    """扫描源头种子（需先有 source_extract/structures.json）."""
    from stock_news.commands.source import scan_sources

    scan_sources(
        date_str=date_str,
        since_minutes=since_minutes,
        start_str=start_str,
        end_str=end_str,
        as_of_str=as_of_str,
        lookback_days=lookback_days,
        top=top,
        max_message_chars=max_message_chars,
        include_closed=include_closed,
        json_output=ctx.obj["json_output"],
        write_markdown=write_markdown,
        markdown_out=markdown_out,
        use_llm_brief=use_llm_brief,
    )
