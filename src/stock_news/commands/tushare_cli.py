"""Tushare 命令注册。

这里只接线股票基础信息同步和本地查询，不提供历史行情命令。
"""

from __future__ import annotations

import json
from dataclasses import asdict

import click

from stock_news.core.config import load
from stock_news.usecases.market_sync import (
    market_info,
    search_stock_companies,
    sync_stock_companies,
)


@click.group()
@click.pass_context
def tushare(ctx: click.Context) -> None:
    """Tushare 代理和市场基础信息."""


@tushare.command("sync-stocks")
@click.pass_context
def sync_stocks(ctx: click.Context) -> None:
    """同步股票公司和代码到 market.db。"""

    cfg = load()
    summary = sync_stock_companies(cfg.tushare)
    if ctx.obj["json_output"]:
        click.echo(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
        return
    click.echo(f"拉取: {summary.fetched}")
    click.echo(f"新增: {summary.inserted}")
    click.echo(f"更新: {summary.updated}")
    click.echo(f"未变: {summary.unchanged}")


@tushare.command()
@click.argument("keyword")
@click.option("--limit", type=int, default=20, help="最多返回条数")
@click.pass_context
def search(ctx: click.Context, keyword: str, limit: int) -> None:
    """搜索本地股票公司和代码。"""

    cfg = load()
    rows = search_stock_companies(cfg.tushare, keyword, limit=limit)
    if ctx.obj["json_output"]:
        click.echo(
            json.dumps([asdict(item) for item in rows], ensure_ascii=False, indent=2)
        )
        return
    if not rows:
        click.echo(f"未找到: {keyword}")
        return
    for item in rows:
        suffix = f"  {item.industry}" if item.industry else ""
        click.echo(f"{item.ts_code}  {item.symbol}  {item.name}{suffix}")


@tushare.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """查看 market.db 状态。"""

    cfg = load()
    info_data = market_info(cfg.tushare)
    if ctx.obj["json_output"]:
        click.echo(json.dumps(asdict(info_data), ensure_ascii=False, indent=2))
        return
    click.echo(f"数据库: {info_data.db_path}")
    click.echo(f"股票公司: {info_data.stock_companies}")
