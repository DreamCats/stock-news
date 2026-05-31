"""策略快报通用工具."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from stock_news.models import OpinionNode, Recommendation

BULLISH_ACTIONS = {"买入", "加仓", "关注"}
BEARISH_ACTIONS = {"卖出", "减仓", "回避"}
TRADE_TARGET_TYPE = "stock"
STRENGTH_SCORE = {
    "强": 18,
    "高": 18,
    "strong": 18,
    "中": 10,
    "medium": 10,
    "弱": 4,
    "低": 4,
    "low": 4,
}


def _opinion_key(opinion: OpinionNode) -> str:
    return f"{opinion.opinion_id}:{opinion.version}:{opinion.message_id}"


def _rec_time(rec: Recommendation, fallback: datetime) -> datetime:
    return rec.message_time or fallback


def _action_side(action: str) -> str:
    if action in BULLISH_ACTIONS:
        return "bullish"
    if action in BEARISH_ACTIONS:
        return "bearish"
    return "neutral"


def _target_type(rec: Recommendation) -> str:
    return rec.target_type or TRADE_TARGET_TYPE


def _target_name(rec: Recommendation) -> str:
    return rec.target_name or rec.ticker


def _target_key(rec: Recommendation) -> str:
    return f"{_target_type(rec)}:{_target_name(rec)}"


def _short_text(text: str | None, max_len: int = 80) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact if len(compact) <= max_len else compact[: max_len - 1] + "..."


def _unique_texts(texts: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        compact = _short_text(text)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        out.append(compact)
        if len(out) >= limit:
            break
    return out


def _pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "/").replace("\n", " ")
