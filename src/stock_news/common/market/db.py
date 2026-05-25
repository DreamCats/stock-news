"""SQLite 行情缓存层."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from stock_news.common.config import CONFIG_DIR

DB_PATH = CONFIG_DIR / "market.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code    TEXT PRIMARY KEY,
    symbol     TEXT NOT NULL,
    name       TEXT NOT NULL,
    area       TEXT,
    industry   TEXT,
    market     TEXT,
    list_date  TEXT
);

CREATE TABLE IF NOT EXISTS trade_cal (
    cal_date      TEXT PRIMARY KEY,
    is_open       INTEGER NOT NULL,
    pretrade_date TEXT
);

CREATE TABLE IF NOT EXISTS daily_price (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    pre_close  REAL,
    change     REAL,
    pct_chg    REAL,
    vol        REAL,
    amount     REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    pre_close  REAL,
    change     REAL,
    pct_chg    REAL,
    vol        REAL,
    amount     REAL,
    PRIMARY KEY (ts_code, trade_date)
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLES)
    return conn


# -- stock_basic --


def upsert_stock_basic(rows: list[dict]) -> int:
    conn = _conn()
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_basic
               (ts_code, symbol, name, area, industry, market, list_date)
               VALUES (:ts_code, :symbol, :name, :area, :industry, :market, :list_date)""",
            rows,
        )
    count = len(rows)
    conn.close()
    return count


def search_stock(keyword: str) -> list[dict]:
    conn = _conn()
    cur = conn.execute(
        "SELECT ts_code, symbol, name, industry FROM stock_basic WHERE name = ?",
        (keyword,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        cur = conn.execute(
            "SELECT ts_code, symbol, name, industry FROM stock_basic WHERE name LIKE ?",
            (f"%{keyword}%",),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_ts_code(name: str) -> str | None:
    rows = search_stock(name)
    return rows[0]["ts_code"] if rows else None


def stock_basic_count() -> int:
    conn = _conn()
    count = conn.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
    conn.close()
    return count


# -- trade_cal --


def upsert_trade_cal(rows: list[dict]) -> int:
    conn = _conn()
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO trade_cal (cal_date, is_open, pretrade_date)
               VALUES (:cal_date, :is_open, :pretrade_date)""",
            rows,
        )
    count = len(rows)
    conn.close()
    return count


def is_trade_day(dt: date) -> bool:
    conn = _conn()
    cur = conn.execute(
        "SELECT is_open FROM trade_cal WHERE cal_date = ?",
        (dt.strftime("%Y%m%d"),),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return True
    return bool(row[0])


def get_next_n_trade_dates(start: date, n: int) -> list[str]:
    conn = _conn()
    cur = conn.execute(
        """SELECT cal_date FROM trade_cal
           WHERE cal_date > ? AND is_open = 1
           ORDER BY cal_date LIMIT ?""",
        (start.strftime("%Y%m%d"), n),
    )
    dates = [row[0] for row in cur.fetchall()]
    conn.close()
    return dates


def trade_cal_count() -> int:
    conn = _conn()
    count = conn.execute("SELECT COUNT(*) FROM trade_cal").fetchone()[0]
    conn.close()
    return count


# -- daily_price --


def upsert_daily(rows: list[dict], table: str = "daily_price") -> int:
    conn = _conn()
    with conn:
        conn.executemany(
            f"""INSERT OR REPLACE INTO {table}
                (ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount)
                VALUES (:ts_code, :trade_date, :open, :high, :low, :close, :pre_close, :change, :pct_chg, :vol, :amount)""",
            rows,
        )
    count = len(rows)
    conn.close()
    return count


def get_daily(ts_code: str, start_date: str, end_date: str, table: str = "daily_price") -> list[dict]:
    conn = _conn()
    cur = conn.execute(
        f"""SELECT * FROM {table}
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date""",
        (ts_code, start_date, end_date),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def has_daily(ts_code: str, start_date: str, end_date: str, table: str = "daily_price") -> bool:
    conn = _conn()
    cur = conn.execute(
        f"""SELECT COUNT(*) FROM {table}
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?""",
        (ts_code, start_date, end_date),
    )
    count = cur.fetchone()[0]
    conn.close()
    return count > 0
