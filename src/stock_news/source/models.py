"""源头雷达数据结构."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from stock_news.models import RawMessage, Recommendation


class SourceExtractItem(BaseModel):
    message_id: str
    source: str = ""
    sender: str = ""
    message_time: datetime
    group_name: str | None = None
    is_source_candidate: bool = False
    source_type: Literal[
        "new_concept",
        "new_application",
        "policy_catalyst",
        "industry_change",
        "noise",
    ] = "noise"
    terms: list[str] = Field(default_factory=list)
    clean_title: str = ""
    confidence: float = 0.0
    reject_reason: str | None = None
    evidence: str | None = None
    llm_provider: str | None = None


@dataclass(frozen=True)
class MessageRow:
    date: date
    message: RawMessage
    category: str | None
    recommendations: tuple[Recommendation, ...]
    terms: tuple[str, ...]
    triggers: tuple[str, ...]


@dataclass(frozen=True)
class Mention:
    term: str
    row: MessageRow
    stocks: tuple[str, ...]


@dataclass(frozen=True)
class SourceCandidate:
    term: str
    score: float
    signal_type: str
    signal_priority: int
    novelty_level: str
    previous_mentions: int
    later_mentions: int
    later_days: int
    later_groups: int
    later_senders: int
    first: Mention
    first_stock: Mention | None
    stock_names: tuple[str, ...]
    baseline_daily: float = 0.0
    surge_count: int = 0
    surge_groups: int = 0
    surge_ratio: float = 0.0
    # 同源别名：同一条首现消息切出的其它候选词（折叠后挂在主词下）。
    aliases: tuple[str, ...] = ()
    # T+3 事后回看验证：首现后 horizon 天内的真实扩散与个股落地。
    t3_groups: int = 0
    t3_senders: int = 0
    t3_stocks: tuple[str, ...] = ()
    verified: bool = False
    verdict: str = ""


@dataclass(frozen=True)
class SourceScanResult:
    start: date
    end: date
    window_start: datetime | None
    window_end: datetime | None
    lookahead_days: int
    scanned_messages: int
    candidate_count: int
    candidates: tuple[SourceCandidate, ...]
