"""策略快报排序与推荐人可信度."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from stock_news.models import Recommendation

from .utils import (
    STRENGTH_SCORE,
    _rec_time,
    _short_text,
    _target_key,
    _target_name,
    _target_type,
    _unique_texts,
)


def _sender_quality(sender: str, sender_stats: dict[str, dict[str, Any]]) -> float:
    stat = sender_stats.get(sender, {})
    count = int(stat.get("count") or 0)
    win_rate = stat.get("win_rate_t5")
    excess = float(stat.get("avg_excess_t5") or 0)
    win_rate_score = 20.0 if win_rate is None else float(win_rate) * 70
    sample_score = min(count, 20) * 0.75
    excess_score = max(min(excess * 100, 20), -20)
    return win_rate_score + sample_score + excess_score


def _target_quality_score(
    target_recs: list[Recommendation],
    sender_stats: dict[str, dict[str, Any]],
) -> float:
    qualities = [
        _sender_quality(sender, sender_stats)
        for sender in {rec.sender for rec in target_recs}
    ]
    if not qualities:
        return 0.0
    return max(qualities) * 0.7 + (sum(qualities) / len(qualities)) * 0.3


def _strength_score(strength: str) -> float:
    return float(STRENGTH_SCORE.get(strength, 8))


def _build_recommendation_item(
    rec: Recommendation,
    sender_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stat = sender_stats.get(rec.sender, {})
    return {
        "message_id": rec.message_id,
        "target_type": _target_type(rec),
        "target_name": _target_name(rec),
        "ticker": rec.ticker,
        "action": rec.action,
        "raw_action": rec.raw_action,
        "strength": rec.strength,
        "confidence": rec.confidence,
        "sender": rec.sender,
        "message_time": rec.message_time.isoformat() if rec.message_time else None,
        "reasoning": _short_text(rec.reasoning),
        "evidence": _short_text(rec.evidence),
        "risk_note": _short_text(rec.risk_note),
        "sender_30d": {
            "count": stat.get("count"),
            "win_rate_t5": stat.get("win_rate_t5"),
            "avg_ret_t5": stat.get("avg_ret_t5"),
            "avg_excess_t5": stat.get("avg_excess_t5"),
        },
    }


def _build_consensus(
    recs: list[Recommendation],
    sender_stats: dict[str, dict[str, Any]],
    top: int | None,
) -> list[dict[str, Any]]:
    by_target: dict[str, list[Recommendation]] = {}
    for rec in recs:
        by_target.setdefault(_target_key(rec), []).append(rec)

    items: list[dict[str, Any]] = []
    for target_key, target_recs in by_target.items():
        first = target_recs[0]
        senders = sorted({r.sender for r in target_recs})
        actions = Counter(r.action for r in target_recs)
        latest = max(
            (_rec_time(r, datetime.min) for r in target_recs),
            default=datetime.min,
        )
        quality_score = _target_quality_score(target_recs, sender_stats)
        avg_confidence = sum(r.confidence for r in target_recs) / len(target_recs)
        strength = max(_strength_score(r.strength) for r in target_recs)
        score = round(
            quality_score
            + strength * 0.6
            + min(len(senders) - 1, 3) * 3
            + min(len(target_recs), 5),
            2,
        )
        reasons = _unique_texts(
            [r.reasoning or "" for r in target_recs],
            limit=2,
        )
        risks = _unique_texts(
            [r.risk_note or "" for r in target_recs],
            limit=2,
        )
        evidences = _unique_texts(
            [r.evidence or "" for r in target_recs],
            limit=2,
        )
        items.append(
            {
                "target_key": target_key,
                "target_type": _target_type(first),
                "target_name": _target_name(first),
                "ticker": first.ticker,
                "score": score,
                "senders": senders,
                "recommendation_count": len(target_recs),
                "actions": dict(actions),
                "confidence": round(avg_confidence, 3),
                "latest_time": latest.isoformat() if latest != datetime.min else None,
                "reasons": reasons,
                "evidences": evidences,
                "risks": risks,
                "sender_quality_score": round(quality_score, 2),
            }
        )

    ranked = sorted(items, key=lambda item: item["score"], reverse=True)
    return ranked[:top] if top is not None else ranked


def _build_sender_credibility(
    sender_stats: dict[str, dict[str, Any]],
    samples: dict[str, list[str]],
    whitelist: list[str],
    min_count: int,
    min_win_rate: float,
    top: int,
) -> list[dict[str, Any]]:
    whitelist_set = set(whitelist)
    rows: list[dict[str, Any]] = []
    for sender, stat in sender_stats.items():
        count = int(stat.get("count") or 0)
        win_rate = stat.get("win_rate_t5")
        is_whitelisted = sender in whitelist_set
        if not is_whitelisted:
            if count < min_count or win_rate is None:
                continue
            if float(win_rate) < min_win_rate:
                continue
        rows.append(
            {
                "sender": sender,
                "win_rate_t5": win_rate,
                "count": count,
                "samples": samples.get(sender, [])[:3],
                "whitelisted": is_whitelisted,
            }
        )

    rows.sort(
        key=lambda item: (
            1 if item["whitelisted"] else 0,
            float(item["win_rate_t5"] or 0),
            int(item["count"] or 0),
        ),
        reverse=True,
    )
    return rows[:top]
