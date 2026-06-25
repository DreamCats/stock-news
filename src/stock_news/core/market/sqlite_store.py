"""股票基础信息 SQLite 存储。

market.db 当前只保存股票公司和代码映射，暂不保存历史行情。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from stock_news.core.db import sqlite_connection
from stock_news.core.market.models import StockCompany, StockSyncSummary


class MarketSQLiteStore:
    """股票基础信息 SQLite 存储。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def init_schema(self) -> None:
        """初始化 market.db 表结构。"""

        with sqlite_connection(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_companies (
                    ts_code TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    area TEXT NOT NULL DEFAULT '',
                    industry TEXT NOT NULL DEFAULT '',
                    market TEXT NOT NULL DEFAULT '',
                    list_date TEXT NOT NULL DEFAULT '',
                    list_status TEXT NOT NULL DEFAULT 'L',
                    row_hash TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_list_status_column(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_stock_companies_symbol
                ON stock_companies (symbol)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_stock_companies_name
                ON stock_companies (name)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_stock_companies_list_status
                ON stock_companies (list_status)
                """
            )

    def upsert_companies(
        self,
        companies: list[StockCompany],
        *,
        now: datetime | None = None,
    ) -> StockSyncSummary:
        """增量写入股票公司信息。"""

        self.init_schema()
        current = (now or datetime.now().astimezone()).isoformat()
        inserted = 0
        updated = 0
        unchanged = 0

        with sqlite_connection(self.path) as conn:
            for company in companies:
                row = conn.execute(
                    "SELECT row_hash FROM stock_companies WHERE ts_code = ?",
                    (company.ts_code,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO stock_companies (
                            ts_code,
                            symbol,
                            name,
                            area,
                            industry,
                            market,
                            list_date,
                            list_status,
                            row_hash,
                            first_seen_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            company.ts_code,
                            company.symbol,
                            company.name,
                            company.area,
                            company.industry,
                            company.market,
                            company.list_date,
                            company.list_status,
                            company.row_hash,
                            current,
                            current,
                        ),
                    )
                    inserted += 1
                    continue
                if str(row["row_hash"]) == company.row_hash:
                    unchanged += 1
                    continue
                conn.execute(
                    """
                    UPDATE stock_companies
                    SET symbol = ?,
                        name = ?,
                        area = ?,
                        industry = ?,
                        market = ?,
                        list_date = ?,
                        list_status = ?,
                        row_hash = ?,
                        updated_at = ?
                    WHERE ts_code = ?
                    """,
                    (
                        company.symbol,
                        company.name,
                        company.area,
                        company.industry,
                        company.market,
                        company.list_date,
                        company.list_status,
                        company.row_hash,
                        current,
                        company.ts_code,
                    ),
                )
                updated += 1

        return StockSyncSummary(
            fetched=len(companies),
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
        )

    def search(self, keyword: str, *, limit: int = 20) -> list[StockCompany]:
        """按股票代码或名称搜索股票公司。"""

        self.init_schema()
        like = f"%{keyword}%"
        with sqlite_connection(self.path) as conn:
            rows = conn.execute(
                """
                SELECT ts_code,
                       symbol,
                       name,
                       area,
                       industry,
                       market,
                       list_date,
                       list_status
                FROM stock_companies
                WHERE ts_code = ?
                   OR symbol = ?
                   OR name = ?
                   OR name LIKE ?
                ORDER BY
                    CASE
                        WHEN ts_code = ? THEN 0
                        WHEN symbol = ? THEN 1
                        WHEN name = ? THEN 2
                        ELSE 3
                    END,
                    ts_code
                LIMIT ?
                """,
                (
                    keyword,
                    keyword,
                    keyword,
                    like,
                    keyword,
                    keyword,
                    keyword,
                    limit,
                ),
            ).fetchall()
        return [_row_to_company(row) for row in rows]

    def count_companies(self) -> int:
        """返回股票公司数量。"""

        self.init_schema()
        with sqlite_connection(self.path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM stock_companies").fetchone()[0]
        return int(count)

    def _ensure_list_status_column(self, conn: Any) -> None:
        columns = conn.execute("PRAGMA table_info(stock_companies)").fetchall()
        names = {str(row["name"]) for row in columns}
        if "list_status" in names:
            return
        conn.execute(
            "ALTER TABLE stock_companies "
            "ADD COLUMN list_status TEXT NOT NULL DEFAULT 'L'"
        )


def _row_to_company(row: Any) -> StockCompany:
    return StockCompany(
        ts_code=str(row["ts_code"] or ""),
        symbol=str(row["symbol"] or ""),
        name=str(row["name"] or ""),
        area=str(row["area"] or ""),
        industry=str(row["industry"] or ""),
        market=str(row["market"] or ""),
        list_date=str(row["list_date"] or ""),
        list_status=str(row["list_status"] or "L"),
    )
