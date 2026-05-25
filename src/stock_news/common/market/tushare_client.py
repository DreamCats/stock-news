"""Tushare Pro API 封装."""

from __future__ import annotations

import time
from pathlib import Path

import click

from stock_news.common.config import CONFIG_DIR
from stock_news.common.market import db

TOKEN_FILE = CONFIG_DIR / "tushare_token"

_MIN_INTERVAL = 0.15  # 500次/分钟 → 120ms 间隔，留余量
_last_call: float = 0.0


def _throttle() -> None:
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.monotonic()


def _get_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(
        f"Tushare token 未配置。请运行: sn market set-token <YOUR_TOKEN>"
    )


def _api():
    import tushare as ts
    return ts.pro_api(_get_token())


def save_token(token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")


# -- stock_basic --


def sync_stock_basic() -> int:
    pro = _api()
    _throttle()
    df = pro.stock_basic(list_status="L", fields="ts_code,symbol,name,area,industry,market,list_date")
    rows = df.to_dict("records")
    return db.upsert_stock_basic(rows)


# -- trade_cal --


def sync_trade_cal(start_date: str = "20200101", end_date: str = "20271231") -> int:
    pro = _api()
    _throttle()
    df = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "cal_date": r["cal_date"],
            "is_open": int(r["is_open"]),
            "pretrade_date": r.get("pretrade_date", ""),
        })
    return db.upsert_trade_cal(rows)


# -- daily --


def fetch_daily(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    cached = db.get_daily(ts_code, start_date, end_date)
    if cached:
        return cached

    pro = _api()
    _throttle()
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return []
    rows = df.to_dict("records")
    db.upsert_daily(rows)
    return db.get_daily(ts_code, start_date, end_date)


def fetch_daily_batch(ts_codes: list[str], start_date: str, end_date: str) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for code in ts_codes:
        result[code] = fetch_daily(code, start_date, end_date)
    return result


# -- index_daily --


def fetch_index_daily(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    cached = db.get_daily(ts_code, start_date, end_date, table="index_daily")
    if cached:
        return cached

    pro = _api()
    _throttle()
    df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return []
    rows = df.to_dict("records")
    db.upsert_daily(rows, table="index_daily")
    return db.get_daily(ts_code, start_date, end_date, table="index_daily")
