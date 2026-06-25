"""公开研究源每日摘要模型。

这里描述研究源文章输入、LLM 摘要结果和任务执行结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from stock_news.core.aly import AlyPublishResult
from stock_news.core.channels import ChannelSendResult
from stock_news.core.research_sources import ResearchSyncSummary


@dataclass(frozen=True)
class ResearchBriefDocument:
    """供 LLM 摘要使用的一条公开研究内容。"""

    source_id: str
    source_name: str
    title: str
    url: str
    published_at: str
    fetched_at: str
    text_excerpt: str


@dataclass(frozen=True)
class ResearchBriefTheme:
    """LLM 归纳出的一条主线。"""

    name: str
    description: str


@dataclass(frozen=True)
class ResearchBriefItem:
    """LLM 摘要中的重点内容。"""

    source_name: str
    title: str
    url: str
    published_at: str
    reason: str
    key_points: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResearchBriefSummary:
    """公开研究源每日中文摘要。"""

    title: str
    summary: str
    themes: tuple[ResearchBriefTheme, ...] = field(default_factory=tuple)
    items: tuple[ResearchBriefItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResearchDailyBriefTaskResult:
    """公开研究源每日摘要任务结果。"""

    generated_at: datetime
    html_path: Path
    sync_summary: ResearchSyncSummary | None
    documents: tuple[ResearchBriefDocument, ...]
    summary: ResearchBriefSummary
    publish_result: AlyPublishResult | None = None
    send_results: tuple[ChannelSendResult, ...] = field(default_factory=tuple)
