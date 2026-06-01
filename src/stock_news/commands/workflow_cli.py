"""workflow 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def workflow(ctx: click.Context) -> None:
    """盘中增量 workflow."""
    pass


@workflow.command("run")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.option(
    "--window-minutes",
    type=click.IntRange(min=1),
    default=1440,
    show_default=True,
    help="fetch 与策略累计窗口分钟数",
)
@click.option(
    "--window-days",
    type=click.IntRange(min=1),
    default=30,
    show_default=True,
    help="推荐人统计窗口天数",
)
@click.option("--source", "-s", default="all", show_default=True, help="fetch 数据源")
@click.option("--provider", "-p", help="指定 LLM provider")
@click.option("--delivery-target", help="发送到单个 delivery target")
@click.option("--delivery-route", help="发送到 delivery route")
@click.option("--send-empty", is_flag=True, help="无新增有效机会时也发送")
@click.option("--top", type=click.IntRange(min=1), default=5, show_default=True)
@click.option(
    "--min-count",
    type=int,
    default=1,
    show_default=True,
    help="推荐人统计最少样本数",
)
@click.option(
    "--slice-hours",
    type=int,
    default=1,
    show_default=True,
    help="fetch 切片小时数",
)
@click.option("--workers", type=int, default=4, show_default=True, help="fetch 并发数")
@click.option(
    "--strategy-llm",
    is_flag=True,
    help="策略报告使用 LLM 生成候选标的逻辑解释",
)
@click.option("--execute", is_flag=True, help="真实执行；不加时只展示 dry-run 计划")
@click.pass_context
def workflow_run(
    ctx: click.Context,
    date_str: str,
    window_minutes: int,
    window_days: int,
    source: str,
    provider: str | None,
    delivery_target: str | None,
    delivery_route: str | None,
    send_empty: bool,
    top: int,
    min_count: int,
    slice_hours: int,
    workers: int,
    strategy_llm: bool,
    execute: bool,
) -> None:
    """执行一次盘中增量 workflow."""
    from stock_news.commands.workflow import run_workflow

    run_workflow(
        date_str,
        window_minutes,
        window_days,
        source,
        provider,
        delivery_target,
        delivery_route,
        send_empty,
        top,
        min_count,
        slice_hours,
        workers,
        strategy_llm,
        execute,
        ctx.obj["json_output"],
    )


@workflow.command("status")
@click.option("--date", "-d", "date_str", default="today", help="日期")
@click.pass_context
def workflow_status(ctx: click.Context, date_str: str) -> None:
    """查看最近一次 workflow 状态."""
    from stock_news.commands.workflow import workflow_status as _workflow_status

    _workflow_status(date_str, ctx.obj["json_output"])
