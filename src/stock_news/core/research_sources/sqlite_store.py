"""公开研究源 SQLite 增量存储。

这里保存官方研究源 URL、内容 hash、落盘路径和抓取状态，支持重复运行去重。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from stock_news.core.db import sqlite_connection
from stock_news.core.research_sources.models import (
    FetchedResearchDocument,
    ResearchCandidate,
    ResearchDocumentRecord,
)


class ResearchSourceSQLiteStore:
    """公开研究源 SQLite 存储。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def init_schema(self) -> None:
        """初始化研究源记录表。"""

        with sqlite_connection(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_documents (
                    url TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    sitemap_lastmod TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT '',
                    content_sha256 TEXT NOT NULL DEFAULT '',
                    text_path TEXT NOT NULL DEFAULT '',
                    binary_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_research_documents_source
                ON research_documents (source_id, published_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_research_documents_status
                ON research_documents (status)
                """
            )

    def has_current_candidate(self, candidate: ResearchCandidate) -> bool:
        """判断候选 URL 是否已经按相同 sitemap lastmod 成功抓过。"""

        self.init_schema()
        with sqlite_connection(self.path) as conn:
            row = conn.execute(
                """
                SELECT sitemap_lastmod, status
                FROM research_documents
                WHERE url = ?
                """,
                (candidate.url,),
            ).fetchone()
        if row is None:
            return False
        return str(row["status"]) == "success" and (
            not candidate.sitemap_lastmod
            or str(row["sitemap_lastmod"]) == candidate.sitemap_lastmod
        )

    def upsert_document(self, doc: FetchedResearchDocument) -> str:
        """写入抓取成功的研究内容，返回 inserted/updated/unchanged。"""

        self.init_schema()
        current = doc.fetched_at.isoformat()
        with sqlite_connection(self.path) as conn:
            row = conn.execute(
                """
                SELECT content_sha256
                FROM research_documents
                WHERE url = ?
                """,
                (doc.url,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO research_documents (
                        url,
                        source_id,
                        source_name,
                        title,
                        published_at,
                        sitemap_lastmod,
                        content_type,
                        content_sha256,
                        text_path,
                        binary_path,
                        status,
                        error,
                        first_seen_at,
                        updated_at,
                        fetched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', '', ?, ?, ?)
                    """,
                    _doc_values(doc) + (current, current, current),
                )
                return "inserted"

            changed = str(row["content_sha256"]) != doc.content_sha256
            conn.execute(
                """
                UPDATE research_documents
                SET source_id = ?,
                    source_name = ?,
                    title = ?,
                    published_at = ?,
                    sitemap_lastmod = ?,
                    content_type = ?,
                    content_sha256 = ?,
                    text_path = ?,
                    binary_path = ?,
                    status = 'success',
                    error = '',
                    updated_at = ?,
                    fetched_at = ?
                WHERE url = ?
                """,
                (
                    doc.source_id,
                    doc.source_name,
                    doc.title,
                    doc.published_at,
                    doc.sitemap_lastmod,
                    doc.content_type,
                    doc.content_sha256,
                    doc.text_path,
                    doc.binary_path,
                    current,
                    current,
                    doc.url,
                ),
            )
        return "updated" if changed else "unchanged"

    def mark_failure(self, candidate: ResearchCandidate, error: str) -> None:
        """记录单条候选抓取失败，便于后续排查和重试。"""

        self.init_schema()
        current = datetime.now().astimezone().isoformat()
        with sqlite_connection(self.path) as conn:
            row = conn.execute(
                "SELECT first_seen_at FROM research_documents WHERE url = ?",
                (candidate.url,),
            ).fetchone()
            first_seen = str(row["first_seen_at"]) if row is not None else current
            conn.execute(
                """
                INSERT INTO research_documents (
                    url,
                    source_id,
                    source_name,
                    sitemap_lastmod,
                    status,
                    error,
                    first_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 'failure', ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    source_id = excluded.source_id,
                    source_name = excluded.source_name,
                    sitemap_lastmod = excluded.sitemap_lastmod,
                    status = 'failure',
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate.url,
                    candidate.source_id,
                    candidate.source_name,
                    candidate.sitemap_lastmod,
                    error,
                    first_seen,
                    current,
                ),
            )

    def list_documents(
        self,
        *,
        source_id: str | None = None,
        fetched_start: datetime | None = None,
        fetched_end: datetime | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[ResearchDocumentRecord]:
        """按更新时间倒序列出研究内容记录。"""

        self.init_schema()
        clauses: list[str] = []
        params: list[object] = []
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        if fetched_start is not None:
            clauses.append("fetched_at >= ?")
            params.append(fetched_start.isoformat())
        if fetched_end is not None:
            clauses.append("fetched_at < ?")
            params.append(fetched_end.isoformat())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with sqlite_connection(self.path) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    source_id,
                    source_name,
                    url,
                    title,
                    published_at,
                    sitemap_lastmod,
                    content_type,
                    content_sha256,
                    text_path,
                    binary_path,
                    status,
                    error,
                    first_seen_at,
                    updated_at,
                    fetched_at
                FROM research_documents
                {where}
                ORDER BY updated_at DESC, url ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_row_to_record(row) for row in rows]


def _doc_values(doc: FetchedResearchDocument) -> tuple[object, ...]:
    return (
        doc.url,
        doc.source_id,
        doc.source_name,
        doc.title,
        doc.published_at,
        doc.sitemap_lastmod,
        doc.content_type,
        doc.content_sha256,
        doc.text_path,
        doc.binary_path,
    )


def _row_to_record(row: Any) -> ResearchDocumentRecord:
    return ResearchDocumentRecord(
        source_id=str(row["source_id"] or ""),
        source_name=str(row["source_name"] or ""),
        url=str(row["url"] or ""),
        title=str(row["title"] or ""),
        published_at=str(row["published_at"] or ""),
        sitemap_lastmod=str(row["sitemap_lastmod"] or ""),
        content_type=str(row["content_type"] or ""),
        content_sha256=str(row["content_sha256"] or ""),
        text_path=str(row["text_path"] or ""),
        binary_path=str(row["binary_path"] or ""),
        status=str(row["status"] or ""),
        error=str(row["error"] or ""),
        first_seen_at=str(row["first_seen_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        fetched_at=str(row["fetched_at"] or ""),
    )
