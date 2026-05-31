"""strategy 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def strategy(ctx: click.Context) -> None:
    """盘中策略快报."""
    pass


@strategy.command("generate")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option(
    "--window-minutes",
    type=click.IntRange(min=1),
    default=1440,
    show_default=True,
    help="策略累计窗口分钟数",
)
@click.option(
    "--top",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="最多输出候选机会数",
)
@click.option("--with-llm", is_flag=True, help="使用 LLM 生成候选标的逻辑解释")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def strategy_generate(
    ctx: click.Context,
    date_str: str,
    window_minutes: int,
    top: int,
    with_llm: bool,
    provider: str | None,
) -> None:
    """生成策略快报 JSON 和 Markdown."""
    from stock_news.commands.strategy import generate

    generate(date_str, window_minutes, top, ctx.obj["json_output"], with_llm, provider)
