"""市场基础信息 SQLite 存储测试。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stock_news.core.market import MarketSQLiteStore, StockCompany


def test_upsert_companies_tracks_incremental_changes(tmp_path: Path) -> None:
    store = MarketSQLiteStore(tmp_path / "market.db")
    now = datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc)
    first = StockCompany(
        ts_code="600519.SH",
        symbol="600519",
        name="贵州茅台",
        area="贵州",
        industry="白酒",
        market="主板",
        list_date="20010827",
    )

    first_summary = store.upsert_companies([first], now=now)
    same_summary = store.upsert_companies([first], now=now)
    changed_summary = store.upsert_companies(
        [
            StockCompany(
                **{**first.__dict__, "industry": "食品饮料", "list_status": "D"}
            )
        ],
        now=now,
    )

    assert first_summary.inserted == 1
    assert first_summary.updated == 0
    assert first_summary.unchanged == 0
    assert same_summary.inserted == 0
    assert same_summary.updated == 0
    assert same_summary.unchanged == 1
    assert changed_summary.inserted == 0
    assert changed_summary.updated == 1
    assert changed_summary.unchanged == 0
    assert store.count_companies() == 1
    changed = store.search("茅台")[0]
    assert changed.industry == "食品饮料"
    assert changed.list_status == "D"


def test_search_matches_code_symbol_and_name(tmp_path: Path) -> None:
    store = MarketSQLiteStore(tmp_path / "market.db")
    store.upsert_companies(
        [
            StockCompany(ts_code="600519.SH", symbol="600519", name="贵州茅台"),
            StockCompany(ts_code="000001.SZ", symbol="000001", name="平安银行"),
        ]
    )

    assert store.search("600519")[0].name == "贵州茅台"
    assert store.search("000001.SZ")[0].name == "平安银行"
    assert store.search("银行")[0].ts_code == "000001.SZ"


def test_init_schema_migrates_old_table_without_list_status(tmp_path: Path) -> None:
    db_path = tmp_path / "market.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE stock_companies (
                ts_code TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                area TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                market TEXT NOT NULL DEFAULT '',
                list_date TEXT NOT NULL DEFAULT '',
                row_hash TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO stock_companies (
                ts_code,
                symbol,
                name,
                row_hash,
                first_seen_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("000001.SZ", "000001", "平安银行", "old-hash", "old", "old"),
        )

    rows = MarketSQLiteStore(db_path).search("平安")

    assert rows[0].list_status == "L"
