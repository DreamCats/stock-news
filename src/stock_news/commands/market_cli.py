"""market 命令注册."""

from __future__ import annotations

import click


@click.group()
@click.pass_context
def market(ctx: click.Context) -> None:
    """行情数据管理（Tushare + SQLite 缓存）."""
    pass


@market.command("set-token")
@click.argument("token")
def market_set_token(token: str) -> None:
    """设置 Tushare Pro token."""
    from stock_news.commands.market_cmd import set_token

    set_token(token)


@market.command("init")
@click.pass_context
def market_init(ctx: click.Context) -> None:
    """初始化: 同步股票列表 + 交易日历."""
    from stock_news.commands.market_cmd import init

    init(ctx.obj["json_output"])


@market.command("search")
@click.argument("keyword")
@click.pass_context
def market_search(ctx: click.Context, keyword: str) -> None:
    """股票名称搜索，如: sn market search 贵州茅台."""
    from stock_news.commands.market_cmd import search

    search(keyword, ctx.obj["json_output"])


@market.command("price")
@click.argument("ts_code")
@click.option("--start", "start_date", required=True, help="开始日期 YYYYMMDD")
@click.option("--end", "end_date", required=True, help="结束日期 YYYYMMDD")
@click.pass_context
def market_price(
    ctx: click.Context, ts_code: str, start_date: str, end_date: str
) -> None:
    """查询/拉取日线行情."""
    from stock_news.commands.market_cmd import price

    price(ts_code, start_date, end_date, ctx.obj["json_output"])


@market.command("info")
@click.pass_context
def market_info(ctx: click.Context) -> None:
    """查看本地缓存统计."""
    from stock_news.commands.market_cmd import info

    info(ctx.obj["json_output"])
