"""微信数据源 SQLite 增量存储。

这里保存原始消息和已成功拉取的时间窗口，用唯一键支持重复运行时增量写入。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from stock_news.core.wechat.models import TimeWindow, WechatMessage


@dataclass(frozen=True)
class WriteSummary:
    """一次消息写入的增量结果。"""

    total: int
    inserted: int
    duplicated: int


@dataclass(frozen=True)
class WindowFetchState:
    """单个拉取窗口的持久化状态。"""

    source: str
    window: TimeWindow
    status: str
    fetched_at: datetime
    message_count: int
    error: str | None = None


class WechatSQLiteStore:
    """微信原始消息和拉取窗口状态的 SQLite 存储。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def init_schema(self) -> None:
        """初始化 SQLite 表结构。"""

        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wechat_messages (
                    message_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message_time TEXT NOT NULL,
                    content TEXT NOT NULL,
                    group_name TEXT,
                    raw_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_wechat_messages_source_time
                ON wechat_messages (source, message_time)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wechat_fetch_windows (
                    source TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    PRIMARY KEY (source, window_start, window_end)
                )
                """
            )

    def save_messages(
        self, messages: list[WechatMessage], *, now: datetime | None = None
    ) -> WriteSummary:
        """增量写入消息，已存在的 message_id 会被跳过。"""

        self.init_schema()
        current = _iso(now or datetime.now().astimezone())
        inserted = 0
        duplicated = 0
        with self._connection() as conn:
            for message in messages:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO wechat_messages (
                        message_id,
                        source,
                        sender,
                        message_time,
                        content,
                        group_name,
                        raw_json,
                        first_seen_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_id,
                        message.source,
                        message.sender,
                        _iso(message.message_time),
                        message.content,
                        message.group_name,
                        json.dumps(
                            message.raw,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        current,
                        current,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    duplicated += 1
        return WriteSummary(
            total=len(messages),
            inserted=inserted,
            duplicated=duplicated,
        )

    def list_messages(
        self,
        *,
        source: str | None = None,
        window: TimeWindow | None = None,
        limit: int | None = None,
    ) -> list[WechatMessage]:
        """按来源和时间窗口读取消息，主要给后续 usecase 和测试使用。"""

        self.init_schema()
        clauses: list[str] = []
        params: list[object] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if window is not None:
            clauses.append("message_time >= ?")
            clauses.append("message_time < ?")
            params.extend([_iso(window.start), _iso(window.end)])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = "LIMIT ?" if limit is not None else ""
        if limit is not None:
            params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    message_id,
                    source,
                    sender,
                    message_time,
                    content,
                    group_name,
                    raw_json
                FROM wechat_messages
                {where}
                ORDER BY message_time ASC, message_id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def mark_window_success(
        self,
        source: str,
        window: TimeWindow,
        *,
        message_count: int,
        fetched_at: datetime | None = None,
    ) -> None:
        """标记一个窗口已成功拉取。"""

        self._upsert_window(
            source=source,
            window=window,
            status="success",
            fetched_at=fetched_at or datetime.now().astimezone(),
            message_count=message_count,
            error=None,
        )

    def mark_window_failure(
        self,
        source: str,
        window: TimeWindow,
        *,
        error: str,
        fetched_at: datetime | None = None,
    ) -> None:
        """标记一个窗口拉取失败，后续增量计划仍会重试。"""

        self._upsert_window(
            source=source,
            window=window,
            status="failure",
            fetched_at=fetched_at or datetime.now().astimezone(),
            message_count=0,
            error=error,
        )

    def get_window_state(
        self, source: str, window: TimeWindow
    ) -> WindowFetchState | None:
        """读取某个来源和窗口的拉取状态。"""

        self.init_schema()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    source,
                    window_start,
                    window_end,
                    status,
                    fetched_at,
                    message_count,
                    error
                FROM wechat_fetch_windows
                WHERE source = ? AND window_start = ? AND window_end = ?
                """,
                (source, _iso(window.start), _iso(window.end)),
            ).fetchone()
        if row is None:
            return None
        return WindowFetchState(
            source=str(row["source"]),
            window=TimeWindow(
                start=datetime.fromisoformat(str(row["window_start"])),
                end=datetime.fromisoformat(str(row["window_end"])),
            ),
            status=str(row["status"]),
            fetched_at=datetime.fromisoformat(str(row["fetched_at"])),
            message_count=int(row["message_count"]),
            error=cast(str | None, row["error"]),
        )

    def should_fetch_window(
        self,
        source: str,
        window: TimeWindow,
        *,
        now: datetime,
        safety_margin_minutes: int,
    ) -> bool:
        """判断窗口是否需要拉取。

        已成功且超过安全延迟的窗口会跳过；失败或仍接近当前时间的窗口会重拉。
        """

        state = self.get_window_state(source, window)
        if state is None or state.status != "success":
            return True
        safe_after = window.end + timedelta(minutes=safety_margin_minutes)
        return now < safe_after

    def _upsert_window(
        self,
        *,
        source: str,
        window: TimeWindow,
        status: str,
        fetched_at: datetime,
        message_count: int,
        error: str | None,
    ) -> None:
        self.init_schema()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO wechat_fetch_windows (
                    source,
                    window_start,
                    window_end,
                    status,
                    fetched_at,
                    message_count,
                    error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, window_start, window_end) DO UPDATE SET
                    status = excluded.status,
                    fetched_at = excluded.fetched_at,
                    message_count = excluded.message_count,
                    error = excluded.error
                """,
                (
                    source,
                    _iso(window.start),
                    _iso(window.end),
                    status,
                    _iso(fetched_at),
                    message_count,
                    error,
                ),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _row_to_message(row: sqlite3.Row) -> WechatMessage:
    raw_obj: object = json.loads(str(row["raw_json"]))
    raw = cast(dict[str, object], raw_obj) if isinstance(raw_obj, dict) else {}
    return WechatMessage(
        message_id=str(row["message_id"]),
        source=str(row["source"]),
        sender=str(row["sender"]),
        message_time=datetime.fromisoformat(str(row["message_time"])),
        content=str(row["content"]),
        group_name=cast(str | None, row["group_name"]),
        raw=raw,
    )


def _iso(value: datetime) -> str:
    return value.isoformat()
