"""源头雷达数据结构."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stock_news.models import RawMessage, Recommendation


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


@dataclass(frozen=True)
class SourceScanResult:
    start: date
    end: date
    lookahead_days: int
    scanned_messages: int
    candidate_count: int
    candidates: tuple[SourceCandidate, ...]
