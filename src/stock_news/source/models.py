"""源头雷达数据结构."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from stock_news.models import RawMessage, Recommendation


class SourceStructureItem(BaseModel):
    """阶段二源头结构抽取产物：只保存可回指原文的组合结构."""

    message_id: str
    source: str = ""
    sender: str = ""
    message_time: datetime
    group_name: str | None = None
    is_candidate: bool = False
    anchor_span: str = ""
    modifier_span: str = ""
    novel_span: str = ""
    relation_type: Literal[
        "A化B",
        "prefix-anchor",
        "modifier-anchor",
        "anchor-extension",
        "other",
    ] = "other"
    relation_evidence: str = ""
    ask_question: str = ""
    confidence: float = 0.0
    reject_reason: str | None = None
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
class SourceSeedCandidate:
    """新源头雷达候选：围绕“成熟锚点 + 陌生组合”的 as-of 证据."""

    signal_id: str
    status: str
    anchor_span: str
    modifier_span: str
    novel_span: str
    relation_type: str
    score: float
    novelty_strength: float
    earliness_score: float
    askability_score: float
    trade_potential_score: float
    first: Mention
    prior_anchor_mentions: int
    prior_modifier_mentions: int
    prior_exact_mentions: int
    prior_combo_mentions: int
    asof_mentions: int
    asof_groups: int
    asof_senders: int
    followup_groups: int
    followup_senders: int
    mapped_stocks: tuple[str, ...]
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceSeedResult:
    start: date
    end: date
    as_of_time: datetime
    window_start: datetime | None
    window_end: datetime | None
    lookback_days: int
    scanned_messages: int
    candidate_count: int
    candidates: tuple[SourceSeedCandidate, ...]
    total_candidate_count: int = 0
    hidden_count: int = 0
