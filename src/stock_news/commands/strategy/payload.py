"""策略快报结构化 payload 聚合."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from stock_news.commands.analyze._common import load_recommendations, parse_date
from stock_news.models import OpinionNode, Recommendation, StrategyConfig

from .scoring import (
    _build_consensus,
    _build_recommendation_item,
    _build_sender_credibility,
)
from .storage import (
    _load_opinions,
    _load_sender_stats,
    _load_sender_win_samples,
    _load_state,
)
from .utils import (
    TRADE_TARGET_TYPE,
    _action_side,
    _opinion_key,
    _rec_time,
    _target_key,
    _target_name,
    _target_type,
    _unique_texts,
)


def _build_opinion_changes(
    opinions: list[OpinionNode],
    seen_opinion_keys: set[str],
    top: int,
) -> list[dict[str, Any]]:
    changed_types = {"new", "reinforce", "revise", "reverse", "withdraw"}
    changes = [
        opinion
        for opinion in opinions
        if _opinion_key(opinion) not in seen_opinion_keys
        and opinion.update_type in changed_types
    ]
    return [
        {
            "key": _opinion_key(opinion),
            "sender": opinion.sender,
            "topic_key": opinion.topic_key,
            "stance": opinion.stance,
            "update_type": opinion.update_type,
            "summary": opinion.summary,
            "confidence": opinion.confidence,
            "candidate_existing_topic": opinion.candidate_existing_topic,
            "message_id": opinion.message_id,
        }
        for opinion in changes[-top:]
    ]


def _build_conflicts(
    recs: list[Recommendation],
    opinions: list[OpinionNode],
    top: int,
) -> list[dict[str, Any]]:
    by_target: dict[str, dict[str, Any]] = {}
    for rec in recs:
        key = _target_name(rec)
        item = by_target.setdefault(
            key,
            {
                "target_key": _target_key(rec),
                "target_type": _target_type(rec),
                "target_name": _target_name(rec),
                "sides": set(),
            },
        )
        item["sides"].add(_action_side(rec.action))
    for opinion in opinions:
        key = opinion.topic_key
        item = by_target.setdefault(
            key,
            {
                "target_key": f"opinion:{opinion.topic_key}",
                "target_type": "opinion",
                "target_name": opinion.topic_key,
                "sides": set(),
            },
        )
        item["sides"].add(opinion.stance)

    conflicts = []
    for item in by_target.values():
        sides = item["sides"]
        if "bullish" in sides and "bearish" in sides:
            conflicts.append(
                {
                    "target_key": item["target_key"],
                    "target_type": item["target_type"],
                    "target_name": item["target_name"],
                    "sides": sorted(sides),
                }
            )
    return conflicts[:top]


def _build_candidate_trades(
    consensus: list[dict[str, Any]],
    opinion_changes: list[dict[str, Any]],
    top: int,
) -> list[dict[str, Any]]:
    changes_by_topic: dict[str, list[dict[str, Any]]] = {}
    for change in opinion_changes:
        changes_by_topic.setdefault(str(change["topic_key"]), []).append(change)

    candidates = []
    for item in consensus:
        if item["target_type"] != TRADE_TARGET_TYPE:
            continue
        sides = {_action_side(action) for action in item["actions"]}
        if "bullish" not in sides:
            continue
        why = [f"{item['recommendation_count']} 条推荐"]
        if len(item["senders"]) > 1:
            why.append(f"{len(item['senders'])} 位推荐人共识")
        changes = changes_by_topic.get(str(item["target_name"]), [])
        if changes:
            why.extend(f"观点 {c['update_type']}" for c in changes[:2])
        candidates.append(
            {
                "target_type": item["target_type"],
                "target_name": item["target_name"],
                "ticker": item["ticker"],
                "score": item["score"],
                "confidence": item["confidence"],
                "why_selected": why,
                "reasons": item["reasons"],
                "evidences": item["evidences"],
                "risks": item["risks"],
                "senders": item["senders"],
            }
        )
        if len(candidates) >= top:
            break
    return candidates


def _build_theme_clues(
    consensus: list[dict[str, Any]],
    top: int,
) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for item in consensus:
        if item["target_type"] == TRADE_TARGET_TYPE:
            continue
        clue = by_name.setdefault(
            item["target_name"],
            {
                "target_types": [],
                "target_name": item["target_name"],
                "score": 0.0,
                "confidence_total": 0.0,
                "confidence_count": 0,
                "recommendation_count": 0,
                "reasons": [],
                "evidences": [],
                "risks": [],
                "senders": [],
            },
        )
        clue["target_types"].append(item["target_type"])
        clue["score"] = max(float(clue["score"]), float(item["score"]))
        clue["confidence_total"] += float(item["confidence"])
        clue["confidence_count"] += 1
        clue["recommendation_count"] += int(item["recommendation_count"])
        clue["reasons"].extend(item["reasons"])
        clue["evidences"].extend(item["evidences"])
        clue["risks"].extend(item["risks"])
        clue["senders"].extend(item["senders"])

    clues: list[dict[str, Any]] = []
    for clue in by_name.values():
        senders = sorted(set(clue["senders"]))
        target_types = sorted(set(clue["target_types"]))
        why = [f"{clue['recommendation_count']} 条线索"]
        if len(senders) > 1:
            why.append(f"{len(senders)} 位推荐人共识")
        clues.append(
            {
                "target_type": "/".join(target_types),
                "target_name": clue["target_name"],
                "score": round(float(clue["score"]), 2),
                "confidence": round(
                    float(clue["confidence_total"]) / int(clue["confidence_count"]),
                    3,
                ),
                "why_selected": why,
                "reasons": _unique_texts(clue["reasons"], limit=2),
                "evidences": _unique_texts(clue["evidences"], limit=2),
                "risks": _unique_texts(clue["risks"], limit=2),
                "senders": senders,
            }
        )
    return sorted(clues, key=lambda item: item["score"], reverse=True)[:top]


def _build_payload(
    data_dir: str,
    date_str: str,
    window_minutes: int,
    top: int,
    report_time: datetime,
    strategy_cfg: StrategyConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    strategy_cfg = strategy_cfg or StrategyConfig()
    dt = parse_date(date_str)
    dt_str = dt.isoformat()
    window_start = report_time - timedelta(minutes=window_minutes)

    recs = load_recommendations(data_dir, dt)
    opinions = _load_opinions(data_dir, dt_str)
    sender_stats = _load_sender_stats(data_dir)
    state = _load_state(data_dir, dt_str)
    seen_message_ids = set(state.get("message_ids") or [])
    seen_opinion_keys = set(state.get("opinion_keys") or [])

    first_run = not seen_message_ids and not seen_opinion_keys
    window_recs = [rec for rec in recs if _rec_time(rec, report_time) >= window_start]
    new_recs = [
        rec
        for rec in recs
        if rec.message_id not in seen_message_ids
        and (not first_run or _rec_time(rec, report_time) >= window_start)
    ]

    new_rec_ids = {rec.message_id for rec in new_recs}
    opinion_changes = _build_opinion_changes(opinions, seen_opinion_keys, top)
    if first_run:
        opinion_changes = [
            item for item in opinion_changes if item["message_id"] in new_rec_ids
        ]

    consensus_all = _build_consensus(window_recs, sender_stats, None)
    consensus = consensus_all[:top]
    conflicts = _build_conflicts(new_recs, opinions, top)
    candidates = _build_candidate_trades(consensus_all, opinion_changes, top)
    theme_clues = _build_theme_clues(consensus_all, top)
    involved_senders = sorted(
        {
            sender
            for item in candidates + theme_clues
            for sender in item.get("senders", [])
        }
    )
    involved_stats = {
        sender: sender_stats[sender]
        for sender in involved_senders
        if sender in sender_stats
    }
    win_samples = _load_sender_win_samples(data_dir, set(involved_senders))
    sender_credibility = _build_sender_credibility(
        involved_stats,
        win_samples,
        strategy_cfg.sender_whitelist,
        strategy_cfg.sender_min_count,
        strategy_cfg.sender_min_win_rate,
        top,
    )

    payload = {
        "report_time": report_time.isoformat(timespec="seconds"),
        "date": dt_str,
        "window": {
            "minutes": window_minutes,
            "start": window_start.isoformat(timespec="seconds"),
            "end": report_time.isoformat(timespec="seconds"),
        },
        "has_updates": bool(new_recs or opinion_changes),
        "window_recommendation_count": len(window_recs),
        "new_recommendations": [
            _build_recommendation_item(rec, sender_stats) for rec in new_recs
        ],
        "top_consensus": consensus,
        "opinion_changes": opinion_changes,
        "conflicts": conflicts,
        "sender_stats": involved_stats,
        "sender_credibility": sender_credibility,
        "candidate_trades": candidates,
        "theme_clues": theme_clues,
    }
    next_state = {
        "generated_at": report_time.isoformat(timespec="seconds"),
        "message_ids": sorted(seen_message_ids | {rec.message_id for rec in recs}),
        "opinion_keys": sorted(seen_opinion_keys | {_opinion_key(o) for o in opinions}),
    }
    return payload, next_state
