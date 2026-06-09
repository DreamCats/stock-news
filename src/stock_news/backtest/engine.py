"""单条推荐回测计算."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from stock_news.backtest.constants import BENCHMARK, WINDOWS
from stock_news.backtest.utils import is_bullish
from stock_news.models import Recommendation


def resolve_ticker(name: str) -> str | None:
    """股票名称 → ts_code，匹配不上返回 None."""
    from stock_news.common.market.db import get_ts_code

    return get_ts_code(name)


def mature_windows(rec_dt: date, as_of: date) -> list[int]:
    """返回 as_of 当天已经成熟的 T+N 窗口."""
    from stock_news.common.market.db import get_next_n_trade_dates

    future_dates = get_next_n_trade_dates(rec_dt, max(WINDOWS))
    return [
        window
        for window in WINDOWS
        if window <= len(future_dates)
        and future_dates[window - 1] <= as_of.strftime("%Y%m%d")
    ]


def backtest_one(
    rec: Recommendation,
    ts_code: str,
    rec_date: str,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """对单条推荐做回测，返回各窗口收益率."""
    from stock_news.common.market.db import get_next_n_trade_dates
    from stock_news.common.market.tushare_client import fetch_daily, fetch_index_daily

    rec_dt = date(int(rec_date[:4]), int(rec_date[4:6]), int(rec_date[6:8]))
    base_rows = fetch_daily(ts_code, rec_date, rec_date)
    if not base_rows:
        start_minus = (rec_dt - timedelta(days=5)).strftime("%Y%m%d")
        base_rows = fetch_daily(ts_code, start_minus, rec_date)
        if not base_rows:
            return None
    base_close = base_rows[-1]["close"]

    future_dates = get_next_n_trade_dates(rec_dt, max(WINDOWS))
    if not future_dates:
        return None

    if as_of is not None:
        mature = mature_windows(rec_dt, as_of)
        if not mature:
            return None
    else:
        mature = WINDOWS

    max_window = max(mature)
    end_date = future_dates[max_window - 1]
    future_rows = fetch_daily(ts_code, future_dates[0], end_date)
    price_map = {row["trade_date"]: row["close"] for row in future_rows}

    bench_base_rows = fetch_index_daily(BENCHMARK, rec_date, rec_date)
    if not bench_base_rows:
        start_minus = (rec_dt - timedelta(days=5)).strftime("%Y%m%d")
        bench_base_rows = fetch_index_daily(BENCHMARK, start_minus, rec_date)
    bench_base = bench_base_rows[-1]["close"] if bench_base_rows else None

    bench_rows = (
        fetch_index_daily(BENCHMARK, future_dates[0], end_date) if bench_base else []
    )
    bench_map = {row["trade_date"]: row["close"] for row in bench_rows}

    bullish = is_bullish(rec.action)
    results: dict[str, object] = {
        "message_id": rec.message_id,
        "ts_code": ts_code,
        "ticker": rec.ticker,
        "sender": rec.sender,
        "action": rec.action,
        "strength": rec.strength,
        "rec_date": rec_date,
        "base_close": base_close,
    }

    for window in mature:
        if window > len(future_dates):
            break
        target_date = future_dates[window - 1]
        results[f"target_date_t{window}"] = target_date
        if target_date not in price_map:
            results[f"ret_t{window}"] = None
            results[f"win_t{window}"] = None
            results[f"bench_ret_t{window}"] = None
            results[f"excess_t{window}"] = None
            results[f"unavailable_t{window}"] = "missing_price"
            continue

        ret = (price_map[target_date] - base_close) / base_close
        win = (ret > 0) if bullish else (ret < 0)

        bench_ret = None
        excess = None
        if bench_base and target_date in bench_map:
            bench_ret = (bench_map[target_date] - bench_base) / bench_base
            excess = ret - bench_ret

        results[f"ret_t{window}"] = round(ret, 6)
        results[f"win_t{window}"] = win
        results[f"bench_ret_t{window}"] = (
            round(bench_ret, 6) if bench_ret is not None else None
        )
        results[f"excess_t{window}"] = round(excess, 6) if excess is not None else None

    return results
