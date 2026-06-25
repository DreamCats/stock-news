"""公开研究源抓取能力。

这里暴露官方 sitemap 增量发现、页面/PDF 抓取和 SQLite 存储接口。
"""

from stock_news.core.research_sources.fetcher import (
    ResearchSourceFetcher,
    extract_html_text,
    serialize_sync_summary,
)
from stock_news.core.research_sources.models import (
    FetchedResearchDocument,
    ResearchCandidate,
    ResearchDocumentRecord,
    ResearchSyncError,
    ResearchSyncSummary,
)
from stock_news.core.research_sources.sqlite_store import ResearchSourceSQLiteStore

__all__ = [
    "FetchedResearchDocument",
    "ResearchCandidate",
    "ResearchDocumentRecord",
    "ResearchSourceFetcher",
    "ResearchSourceSQLiteStore",
    "ResearchSyncError",
    "ResearchSyncSummary",
    "extract_html_text",
    "serialize_sync_summary",
]
