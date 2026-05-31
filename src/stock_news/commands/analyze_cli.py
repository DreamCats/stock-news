"""analyze 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def analyze(ctx: click.Context) -> None:
    """消息分析（分类、抽取、观点链）."""
    pass


@analyze.command()
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--no-llm", is_flag=True, help="不使用 LLM，降级为规则分类")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def classify(
    ctx: click.Context, date_str: str, no_llm: bool, provider: str | None
) -> None:
    """对消息做分类."""
    from stock_news.commands.analyze import classify as _classify

    _classify(date_str, no_llm, provider, ctx.obj["json_output"])


@analyze.command()
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def extract(ctx: click.Context, date_str: str, provider: str | None) -> None:
    """从推荐消息中抽取结构化字段."""
    from stock_news.commands.analyze import extract as _extract

    _extract(date_str, provider, ctx.obj["json_output"])


@analyze.command("opinion")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def opinion_cmd(ctx: click.Context, date_str: str, provider: str | None) -> None:
    """分析观点链变化."""
    from stock_news.commands.analyze import opinion as _opinion

    _opinion(date_str, provider, ctx.obj["json_output"])


@analyze.command("show")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.pass_context
def analyze_show(ctx: click.Context, date_str: str) -> None:
    """查看分析摘要."""
    from stock_news.commands.analyze import show_analysis

    show_analysis(date_str, ctx.obj["json_output"])


@analyze.command("pipeline")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option("--no-llm", is_flag=True, help="不使用 LLM，降级为规则分类")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.pass_context
def analyze_pipeline(
    ctx: click.Context, date_str: str, no_llm: bool, provider: str | None
) -> None:
    """一键执行: 分类 → 抽取 → 回测."""
    from stock_news.commands.analyze import pipeline as _pipeline

    _pipeline(date_str, no_llm, provider, ctx.obj["json_output"])


@analyze.group("backtest", invoke_without_command=True)
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.pass_context
def analyze_backtest(ctx: click.Context, date_str: str) -> None:
    """回测推荐人胜率（需先 sn market init）."""
    if ctx.invoked_subcommand is not None:
        return
    from stock_news.commands.backtest import run_backtest

    run_backtest(date_str, ctx.obj["json_output"])


@analyze_backtest.command("refresh")
@click.option(
    "--as-of",
    "as_of_str",
    default="today",
    show_default=True,
    help="刷新到哪一天",
)
@click.option(
    "--window-days",
    type=click.IntRange(min=1),
    default=30,
    show_default=True,
    help="扫描最近 N 天推荐",
)
@click.pass_context
def analyze_backtest_refresh(
    ctx: click.Context,
    as_of_str: str,
    window_days: int,
) -> None:
    """刷新已成熟的 T+N 回测窗口."""
    from stock_news.commands.backtest import run_backtest_refresh

    run_backtest_refresh(as_of_str, window_days, ctx.obj["json_output"])


@analyze_backtest.command("summary")
@click.option("--top", "-n", type=int, default=None, help="只显示前 N 名")
@click.option(
    "--min-count",
    type=int,
    default=1,
    help="最少推荐次数（过滤样本量不足的）",
)
@click.option(
    "--window-days",
    type=click.IntRange(min=1),
    default=30,
    show_default=True,
    help="汇总最近 N 天",
)
@click.option("--all", "include_all", is_flag=True, help="汇总所有已有回测结果")
@click.pass_context
def analyze_backtest_summary(
    ctx: click.Context,
    top: int | None,
    min_count: int,
    window_days: int,
    include_all: bool,
) -> None:
    """汇总近期回测结果，输出推荐人滚动胜率."""
    from stock_news.commands.backtest import run_backtest_summary

    run_backtest_summary(
        ctx.obj["json_output"],
        top=top,
        min_count=min_count,
        window_days=None if include_all else window_days,
    )
