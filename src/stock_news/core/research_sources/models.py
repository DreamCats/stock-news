"""公开研究源数据模型。

这些模型描述官方研究源的发现候选、抓取结果和增量同步摘要。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ResearchCandidate:
    """从 sitemap 发现的一条候选研究内容。"""

    source_id: str
    source_name: str
    url: str
    sitemap_lastmod: str = ""


@dataclass(frozen=True)
class FetchedResearchDocument:
    """已经抓取并落盘的一条研究内容。"""

    source_id: str
    source_name: str
    url: str
    title: str
    published_at: str
    sitemap_lastmod: str
    content_type: str
    content_sha256: str
    text_path: str
    binary_path: str
    fetched_at: datetime


@dataclass(frozen=True)
class ResearchDocumentRecord:
    """SQLite 中保存的一条研究内容记录。"""

    source_id: str
    source_name: str
    url: str
    title: str
    published_at: str
    sitemap_lastmod: str
    content_type: str
    content_sha256: str
    text_path: str
    binary_path: str
    status: str
    error: str
    first_seen_at: str
    updated_at: str
    fetched_at: str


@dataclass(frozen=True)
class ResearchSyncError:
    """单条研究内容同步失败信息。"""

    source_id: str
    url: str
    error: str


@dataclass(frozen=True)
class ResearchSyncSummary:
    """一次公开研究源同步的增量结果。"""

    sources: int
    candidates: int
    fetched: int
    inserted: int
    updated: int
    unchanged: int
    skipped: int
    failed: int
    dry_run: bool
    errors: list[ResearchSyncError]
