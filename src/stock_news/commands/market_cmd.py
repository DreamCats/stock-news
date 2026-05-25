"""行情数据管理命令."""

from __future__ import annotations

import json

import click


def set_token(token: str) -> None:
    from stock_news.common.market.tushare_client import save_token
    save_token(token)
    click.echo("Tushare token 已保存")


def init(json_output: bool) -> None:
    from stock_news.common.market import db
    from stock_news.common.market.tushare_client import sync_stock_basic, sync_trade_cal

    click.echo("正在同步 stock_basic...", err=True)
    n_stocks = sync_stock_basic()
    click.echo(f"  stock_basic: {n_stocks} 条", err=True)

    click.echo("正在同步 trade_cal...", err=True)
    n_cal = sync_trade_cal()
    click.echo(f"  trade_cal: {n_cal} 条", err=True)

    if json_output:
        click.echo(json.dumps({"stock_basic": n_stocks, "trade_cal": n_cal}))
    else:
        click.echo(f"初始化完成: {n_stocks} 只股票, {n_cal} 个日历日")


def search(keyword: str, json_output: bool) -> None:
    from stock_news.common.market.db import search_stock

    rows = search_stock(keyword)
    if json_output:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        click.echo(f"未找到匹配: {keyword}")
        return
    for r in rows:
        click.echo(f"  {r['ts_code']}  {r['name']}  {r.get('industry', '')}")


def price(ts_code: str, start_date: str, end_date: str, json_output: bool) -> None:
    from stock_news.common.market.tushare_client import fetch_daily

    rows = fetch_daily(ts_code, start_date, end_date)
    if json_output:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        click.echo(f"无数据: {ts_code} {start_date}-{end_date}")
        return
    click.echo(f"{ts_code} 共 {len(rows)} 条日线:")
    for r in rows[-10:]:
        click.echo(f"  {r['trade_date']}  O:{r['open']}  H:{r['high']}  L:{r['low']}  C:{r['close']}  pct:{r['pct_chg']}%")
    if len(rows) > 10:
        click.echo(f"  ... 仅显示最近 10 条")


def info(json_output: bool) -> None:
    from stock_news.common.market.db import stock_basic_count, trade_cal_count

    n_stocks = stock_basic_count()
    n_cal = trade_cal_count()
    if json_output:
        click.echo(json.dumps({"stock_basic": n_stocks, "trade_cal": n_cal}))
    else:
        click.echo(f"stock_basic: {n_stocks} 条\ntrade_cal: {n_cal} 条\n数据库: ~/.config/stock-news/market.db")
