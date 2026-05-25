"""一键执行: classify → extract → backtest."""

from __future__ import annotations

import time

import click

from stock_news.commands.analyze.classify import classify
from stock_news.commands.analyze.extract import extract


def pipeline(
    date_str: str,
    no_llm: bool,
    provider_name: str | None,
    json_output: bool,
) -> None:
    """一键执行: classify → extract → backtest."""
    t0 = time.time()

    if not json_output:
        click.echo(f"=== Pipeline 开始: {date_str} ===\n", err=True)

    # 1. classify
    if not json_output:
        click.echo("[1/3] 消息分类...", err=True)
    classify(date_str, no_llm, provider_name, json_output=False if not json_output else True)
    t1 = time.time()
    if not json_output:
        click.echo(f"  ✓ 分类完成 ({t1 - t0:.0f}s)\n", err=True)

    # 2. extract
    if not json_output:
        click.echo("[2/3] 推荐抽取...", err=True)
    extract(date_str, provider_name, json_output=False if not json_output else True)
    t2 = time.time()
    if not json_output:
        click.echo(f"  ✓ 抽取完成 ({t2 - t1:.0f}s)\n", err=True)

    # 3. backtest
    if not json_output:
        click.echo("[3/3] 回测...", err=True)
    from stock_news.commands.backtest import run_backtest
    run_backtest(date_str, json_output=False if not json_output else True)
    t3 = time.time()
    if not json_output:
        click.echo(f"  ✓ 回测完成 ({t3 - t2:.0f}s)\n", err=True)

    total = t3 - t0
    if not json_output:
        click.echo(f"=== Pipeline 完成: 总耗时 {total:.0f}s ({total/60:.1f}min) ===", err=True)
