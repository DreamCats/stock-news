"""盘中策略快报生成."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import click

from stock_news.commands.analyze._common import (
    load_recommendations,
    parse_date,
)
from stock_news.common.config import load
from stock_news.models import OpinionNode, Recommendation

BULLISH_ACTIONS = {"买入", "加仓", "关注"}
BEARISH_ACTIONS = {"卖出", "减仓", "回避"}
TRADE_TARGET_TYPE = "stock"
TARGET_TYPE_LABELS = {
    "stock": "个股",
    "sector": "板块",
    "theme": "主题",
    "macro": "宏观",
    "index": "指数",
    "unknown": "未知",
    "opinion": "观点",
}
UPDATE_TYPE_LABELS = {
    "new": "首次提出",
    "reinforce": "强化",
    "supplement": "补充",
    "revise": "修正",
    "reverse": "反转",
    "withdraw": "撤回",
}
STANCE_LABELS = {
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "中性",
    "mixed": "分歧",
}
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


def _date_dir(data_dir: str, dt_str: str) -> Path:
    return Path(data_dir).expanduser() / dt_str


def _strategy_dir(data_dir: str, dt_str: str) -> Path:
    d = _date_dir(data_dir, dt_str) / "strategy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_opinions(data_dir: str, dt_str: str) -> list[OpinionNode]:
    path = _date_dir(data_dir, dt_str) / "opinions" / "opinions.json"
    data = _load_json(path, [])
    if not isinstance(data, list):
        return []
    return [OpinionNode.model_validate(item) for item in data]


def _load_sender_stats(data_dir: str) -> dict[str, dict[str, Any]]:
    path = Path(data_dir).expanduser() / "backtest_summary" / "sender_stats.json"
    data = _load_json(path, [])
    if not isinstance(data, list):
        return {}
    return {
        str(item.get("sender")): item
        for item in data
        if isinstance(item, dict) and item.get("sender")
    }


def _load_state(data_dir: str, dt_str: str) -> dict[str, Any]:
    data = _load_json(_strategy_dir(data_dir, dt_str) / "state.json", {})
    return data if isinstance(data, dict) else {}


def _save_outputs(
    data_dir: str,
    dt_str: str,
    payload: dict[str, Any],
    markdown: str,
    state: dict[str, Any],
) -> tuple[Path, Path]:
    out_dir = _strategy_dir(data_dir, dt_str)
    json_path = out_dir / "strategy.json"
    md_path = out_dir / "strategy.md"
    state_path = out_dir / "state.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path, md_path


def _opinion_key(opinion: OpinionNode) -> str:
    return f"{opinion.opinion_id}:{opinion.version}:{opinion.message_id}"


def _rec_time(rec: Recommendation, fallback: datetime) -> datetime:
    return rec.message_time or fallback


def _sender_quality(sender: str, sender_stats: dict[str, dict[str, Any]]) -> float:
    stat = sender_stats.get(sender, {})
    count = int(stat.get("count") or 0)
    win_rate = float(stat.get("win_rate_t5") or 0)
    excess = float(stat.get("avg_excess_t5") or 0)
    sample_score = min(count, 10) * 1.5
    return win_rate * 30 + sample_score + excess * 100


def _strength_score(strength: str) -> float:
    return float(STRENGTH_SCORE.get(strength, 8))


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
        avg_quality = sum(
            _sender_quality(r.sender, sender_stats) for r in target_recs
        ) / len(target_recs)
        avg_confidence = sum(r.confidence for r in target_recs) / len(target_recs)
        strength = max(_strength_score(r.strength) for r in target_recs)
        score = round(
            len(senders) * 20 + avg_quality + strength + avg_confidence * 10,
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
            }
        )

    ranked = sorted(items, key=lambda item: item["score"], reverse=True)
    return ranked[:top] if top is not None else ranked


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


def _fallback_logic(item: dict[str, Any]) -> dict[str, Any]:
    clues = _unique_texts(item.get("evidences") or item.get("reasons") or [], limit=2)
    risks = _unique_texts(item.get("risks") or [], limit=2)
    why = "、".join(str(part) for part in item.get("why_selected", []) if part)
    clue_text = "；".join(clues) if clues else "新增推荐进入候选池"
    score_driver = (
        f"{why or '新增推荐'}让它进入候选前排；"
        "但当前仍是规则模板归纳，缺少 LLM 对产业传导和证伪点的深度整理。"
    )
    return {
        "source": "template",
        "conviction": "待验证",
        "strong_reason": f"{why or '新增推荐'}，核心证据是：{clue_text}。",
        "boss_pitch": (
            f"这个标的值得进入观察清单，主要因为{why or '本轮有新增推荐'}。"
            f"现有证据指向：{clue_text}。"
            "不过目前缺少更完整的产业传导、业绩兑现或事件催化说明，"
            "不能只凭分数视为高确定性强推。"
        ),
        "score_driver": score_driver,
        "logic_chain": [
            f"触发：{why or '本轮新增推荐'}。",
            f"依据：{clue_text}。",
            "待验证：需要补齐产业传导、业绩影响或事件催化。",
        ],
        "information_increment": clue_text,
        "validation_points": [
            "后续是否有更多推荐人或新证据继续强化。",
            "是否出现订单、业绩、价格或事件催化层面的验证。",
        ],
        "risks": risks or ["当前信息仍需后续价格、业绩或事件验证。"],
        "evidence_refs": clues,
    }


def _logic_items_for_llm(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sender_stats = payload.get("sender_stats") or {}
    opinion_changes = payload.get("opinion_changes") or []
    theme_clues = payload.get("theme_clues") or []
    items = []
    for candidate in payload.get("candidate_trades", []):
        target_name = str(candidate.get("target_name") or "")
        related_opinions = [
            {
                "sender": item.get("sender"),
                "stance": item.get("stance"),
                "update_type": item.get("update_type"),
                "summary": item.get("summary"),
                "confidence": item.get("confidence"),
            }
            for item in opinion_changes
            if item.get("topic_key") == target_name
        ][:3]
        related_themes = [
            {
                "target_type": item.get("target_type"),
                "target_name": item.get("target_name"),
                "evidences": item.get("evidences", [])[:2],
                "score": item.get("score"),
            }
            for item in theme_clues
        ][:3]
        items.append(
            {
                "target_name": target_name,
                "ticker": candidate.get("ticker"),
                "score": candidate.get("score"),
                "confidence": candidate.get("confidence"),
                "why_selected": candidate.get("why_selected", []),
                "evidences": candidate.get("evidences", [])[:2],
                "reasons": candidate.get("reasons", [])[:2],
                "risks": candidate.get("risks", [])[:2],
                "senders": candidate.get("senders", [])[:5],
                "sender_stats": {
                    sender: sender_stats.get(sender)
                    for sender in candidate.get("senders", [])[:5]
                    if sender_stats.get(sender)
                },
                "related_opinions": related_opinions,
                "related_theme_clues": related_themes,
            }
        )
    return items


def _texts_for_fact_check(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            compact = " ".join(value.split())
            if compact:
                texts.append(compact)

    collect(payload.get("candidate_trades", []))
    collect(payload.get("theme_clues", []))
    collect(payload.get("opinion_changes", []))
    collect(payload.get("top_consensus", []))
    return texts


def _number_tokens(text: str) -> set[str]:
    import re

    return set(re.findall(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text))


def _unsupported_numbers(text: str, evidence_texts: list[str]) -> list[str]:
    evidence_numbers: set[str] = set()
    for evidence in evidence_texts:
        evidence_numbers.update(_number_tokens(evidence))
    return sorted(_number_tokens(text) - evidence_numbers)


def _drop_unsupported_number_items(
    value: Any,
    evidence_texts: list[str],
) -> tuple[Any, list[str]]:
    removed: list[str] = []
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            checked, item_removed = _drop_unsupported_number_items(
                item,
                evidence_texts,
            )
            removed.extend(item_removed)
            if checked is not None:
                out[key] = checked
        return out, removed
    if isinstance(value, list):
        out_list: list[Any] = []
        for item in value:
            checked, item_removed = _drop_unsupported_number_items(
                item,
                evidence_texts,
            )
            removed.extend(item_removed)
            if checked is not None:
                out_list.append(checked)
        return out_list, removed
    if isinstance(value, str):
        unsupported = _unsupported_numbers(value, evidence_texts)
        if unsupported:
            removed.append(f"{value[:80]} -> {','.join(unsupported)}")
            return None, removed
    return value, removed


def _as_text_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, list):
        texts = [str(item).strip() for item in value if str(item).strip()]
    elif value:
        texts = [str(value).strip()]
    else:
        texts = []
    return [_short_text(text, max_len=90) for text in texts[:limit]]


def _normalize_llm_logic(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "llm",
        "conviction": _short_text(str(item.get("conviction") or ""), max_len=20),
        "boss_pitch": _short_text(str(item.get("boss_pitch") or ""), max_len=360),
        "strong_reason": _short_text(str(item.get("strong_reason") or ""), max_len=120),
        "score_driver": _short_text(str(item.get("score_driver") or ""), max_len=180),
        "logic_chain": _as_text_list(item.get("logic_chain"), limit=4),
        "information_increment": _short_text(
            str(item.get("information_increment") or ""),
            max_len=120,
        ),
        "validation_points": _as_text_list(item.get("validation_points"), limit=3),
        "risks": _as_text_list(item.get("risks"), limit=3),
        "evidence_refs": _as_text_list(item.get("evidence_refs"), limit=3),
    }


def _as_dict_list(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def _normalize_strategy_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "source": "llm",
        "market_summary": _short_text(
            str(value.get("market_summary") or ""),
            max_len=360,
        ),
        "mainlines": _as_dict_list(value.get("mainlines"), limit=3),
        "priority_targets": _as_dict_list(value.get("priority_targets"), limit=4),
        "baskets": _as_dict_list(value.get("baskets"), limit=4),
        "watchlist": _as_dict_list(value.get("watchlist"), limit=6),
    }


def _sanitize_strategy_view(
    value: Any,
    evidence_texts: list[str],
) -> tuple[dict[str, Any], list[str]]:
    normalized = _normalize_strategy_view(value)
    if not normalized:
        return {}, []
    sanitized, removed = _drop_unsupported_number_items(normalized, evidence_texts)
    return _normalize_strategy_view(sanitized), removed


def _generate_llm_logic(
    payload: dict[str, Any],
    provider_name: str | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from stock_news.common.llm.client import chat, get_provider_for_task

    items = _logic_items_for_llm(payload)
    if not items:
        return {}, {}
    evidence_texts = _texts_for_fact_check(payload)
    if provider_name is None:
        provider_name, _ = get_provider_for_task("strategy")

    messages = [
        {
            "role": "system",
            "content": (
                "你是买方投研负责人，写给老板看的盘中策略判断。"
                "你的目标不是逐条复述分数，而是先归纳今日主线，"
                "再说明哪些标的值得优先看、哪些只是同主题篮子。"
                "只能基于用户给出的结构化证据，不要补充外部事实，"
                "不要承诺收益，不要编造订单、业绩、政策或价格。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "生成老板可读的策略主线和强推逻辑。",
                    "output_schema": {
                        "strategy_view": {
                            "market_summary": (
                                "2到4句总结今天最重要的主线，解释为什么这些线索集中出现"
                            ),
                            "mainlines": [
                                {
                                    "name": "主线名称",
                                    "judgment": "这条主线为什么重要",
                                    "targets": ["相关标的"],
                                    "validation": ["验证点"],
                                }
                            ],
                            "priority_targets": [
                                {
                                    "target_name": "最值得优先看的标的",
                                    "thesis": "连续段落说明为什么现在值得看",
                                    "why_now": "今天新增了什么",
                                    "downgrade_trigger": "什么情况降级",
                                }
                            ],
                            "baskets": [
                                {
                                    "theme": "主题篮子名称",
                                    "judgment": "篮子共同逻辑",
                                    "targets": ["同主题标的"],
                                    "differences": "各自角色差异；证据不足则说明难区分",
                                    "validation": ["验证点"],
                                    "risks": ["风险"],
                                }
                            ],
                            "watchlist": [
                                {
                                    "target_name": "观察标的",
                                    "reason": "为什么暂不强推",
                                    "needed_evidence": "需要补什么证据才升级",
                                }
                            ],
                        },
                        "items": [
                            {
                                "target_name": "必须与输入一致",
                                "conviction": "强|中|弱|待验证",
                                "boss_pitch": (
                                    "2到4句连续中文，像投研负责人向老板解释；"
                                    "必须讲清变化、传导、为什么现在值得看、证伪点"
                                ),
                                "strong_reason": "一句话说明为什么优先看",
                                "score_driver": (
                                    "解释为什么排序靠前：共识、证据、观点变化、"
                                    "推荐人历史表现分别贡献了什么"
                                ),
                                "logic_chain": [
                                    "变化/触发",
                                    "传导机制",
                                    "为什么可能影响股价或关注度",
                                ],
                                "information_increment": (
                                    "今天相比历史或普通推荐新增了什么"
                                ),
                                "validation_points": ["后续需要跟踪验证的点"],
                                "risks": ["最可能证伪该逻辑的风险"],
                                "evidence_refs": ["引用输入里的短证据，不要造新事实"],
                            }
                        ],
                    },
                    "requirements": [
                        "只输出纯 JSON，不要 markdown。",
                        "每个字段使用中文。",
                        "禁止输出输入证据里没有的精确数字、比例、产能、金额、时间或事实。",
                        "如果输入没有精确数字，只能写定性判断，不要自行估算或补充。",
                        "strategy_view 是给老板先看的核心内容，必须优先写好。",
                        (
                            "不要把同主题标的逐个重复强推；同主题、同证据、"
                            "同推荐逻辑的标的放进 baskets。"
                        ),
                        (
                            "priority_targets 只放最值得优先看的 2 到 4 个，"
                            "证据薄或单条推荐放 watchlist。"
                        ),
                        "boss_pitch 必须是连续段落，不要写成口号或碎片。",
                        "不要重复使用同一句模板话。",
                        "逻辑链要解释 score 高背后的原因，而不是复述分数。",
                        "如果多个标的来自同一主题，要说明各自角色；"
                        "若输入证据无法区分，就写明只是同主题篮子线索。",
                        "如果证据不足，要明确写证据不足和需要验证什么。",
                    ],
                    "candidates": items,
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = chat(messages, provider_name=provider_name, disable_thinking=False).strip()
    parsed = _parse_logic_response(raw)
    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    strategy_view, removed_facts = _sanitize_strategy_view(
        parsed.get("strategy_view"),
        evidence_texts,
    )
    if not isinstance(raw_items, list):
        if removed_facts:
            strategy_view["fact_check_removed"] = removed_facts
        return {}, strategy_view

    logic_by_name: dict[str, dict[str, Any]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        target_name = str(raw_item.get("target_name") or "").strip()
        if not target_name:
            continue
        logic_by_name[target_name] = _normalize_llm_logic(raw_item)
    if removed_facts:
        strategy_view["fact_check_removed"] = removed_facts
    return logic_by_name, strategy_view


def _parse_logic_response(raw: str) -> dict[str, Any]:
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
    if isinstance(parsed, list):
        return {"items": parsed}
    return parsed if isinstance(parsed, dict) else {}


def _attach_candidate_logic(
    payload: dict[str, Any],
    use_llm: bool,
    provider_name: str | None,
) -> None:
    candidates = payload.get("candidate_trades", [])
    logic_by_name: dict[str, dict[str, Any]] = {}
    strategy_view: dict[str, Any] = {}
    logic_error = ""
    if use_llm and candidates:
        try:
            result: Any = _generate_llm_logic(payload, provider_name)
            if isinstance(result, tuple):
                logic_by_name, strategy_view = result
            else:
                logic_by_name = result
            if not logic_by_name:
                logic_error = "LLM 未返回可用强推逻辑，已降级为本地模板。"
        except Exception as exc:  # pragma: no cover - depends on external provider
            logic_error = str(exc)
            click.echo(f"强推逻辑 LLM 生成失败，已使用本地模板: {exc}", err=True)

    for candidate in candidates:
        target_name = str(candidate.get("target_name") or "")
        logic = logic_by_name.get(target_name) or _fallback_logic(candidate)
        candidate["logic"] = logic

    payload["logic_generation"] = {
        "enabled": use_llm,
        "source": "llm" if logic_by_name else "template",
        "error": logic_error or None,
    }
    if strategy_view:
        payload["strategy_view"] = strategy_view


def _build_payload(
    data_dir: str,
    date_str: str,
    window_minutes: int,
    top: int,
    report_time: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
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

    consensus_all = _build_consensus(new_recs, sender_stats, None)
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

    payload = {
        "report_time": report_time.isoformat(timespec="seconds"),
        "date": dt_str,
        "window": {
            "minutes": window_minutes,
            "start": window_start.isoformat(timespec="seconds"),
            "end": report_time.isoformat(timespec="seconds"),
        },
        "has_updates": bool(new_recs or opinion_changes),
        "new_recommendations": [
            _build_recommendation_item(rec, sender_stats) for rec in new_recs
        ],
        "top_consensus": consensus,
        "opinion_changes": opinion_changes,
        "conflicts": conflicts,
        "sender_stats": involved_stats,
        "candidate_trades": candidates,
        "theme_clues": theme_clues,
    }
    next_state = {
        "generated_at": report_time.isoformat(timespec="seconds"),
        "message_ids": sorted(seen_message_ids | {rec.message_id for rec in recs}),
        "opinion_keys": sorted(seen_opinion_keys | {_opinion_key(o) for o in opinions}),
    }
    return payload, next_state


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


def _primary_clue(item: dict[str, Any]) -> str:
    texts = _unique_texts(item.get("evidences") or item.get("reasons") or [], limit=1)
    if not texts:
        return "-"
    return _short_text(str(texts[0]), max_len=56)


def _sender_stat_line(sender: str, stat: dict[str, Any]) -> str:
    count = int(stat.get("count") or 0)
    if count < 5:
        return f"- {sender}：样本 {count}，样本不足"
    return (
        f"- {sender}：样本 {count}，"
        f"T+5 胜率 {_pct(stat.get('win_rate_t5'))}，"
        f"平均超额 {_pct(stat.get('avg_excess_t5'))}"
    )


def _target_type_label(value: str) -> str:
    return "/".join(TARGET_TYPE_LABELS.get(part, part) for part in value.split("/"))


def _update_type_label(value: str) -> str:
    return UPDATE_TYPE_LABELS.get(value, value)


def _stance_label(value: str) -> str:
    return STANCE_LABELS.get(value, value)


def _render_logic_block(item: dict[str, Any]) -> list[str]:
    logic = item.get("logic") or _fallback_logic(item)
    lines = [f"### {item['target_name']}"]
    conviction = logic.get("conviction")
    if conviction:
        lines.append(f"- 逻辑强度：{conviction}")

    boss_pitch = logic.get("boss_pitch")
    if boss_pitch:
        lines.append(f"- 给老板的判断：{boss_pitch}")
    else:
        strong_reason = logic.get("strong_reason")
        if strong_reason:
            lines.append(f"- 给老板的判断：{strong_reason}")

    score_driver = logic.get("score_driver")
    if score_driver:
        lines.append(f"- 为什么排前：{score_driver}")
    else:
        logic_chain = _as_text_list(logic.get("logic_chain"), limit=4)
        if logic_chain:
            lines.append("- 底层逻辑链：" + " → ".join(logic_chain))

    evidence_refs = _as_text_list(logic.get("evidence_refs"), limit=3)
    if evidence_refs:
        lines.append(f"- 关键证据：{'；'.join(evidence_refs)}")

    validation_points = _as_text_list(logic.get("validation_points"), limit=3)
    if validation_points:
        lines.append(f"- 后续验证：{'；'.join(validation_points)}")

    risks = _as_text_list(logic.get("risks"), limit=3)
    if risks:
        lines.append(f"- 主要风险：{'；'.join(risks)}")
    return lines


def _render_strategy_view(payload: dict[str, Any]) -> list[str]:
    view = payload.get("strategy_view")
    if not isinstance(view, dict):
        return []

    lines: list[str] = []
    market_summary = str(view.get("market_summary") or "").strip()
    if market_summary:
        lines.extend(["### 今日主线", f"- {market_summary}"])

    mainlines = _as_dict_list(view.get("mainlines"), limit=3)
    if mainlines:
        lines.append("### 主线拆解")
        for item in mainlines:
            name = _cell(item.get("name"))
            judgment = _short_text(str(item.get("judgment") or ""), max_len=220)
            targets = "、".join(_as_text_list(item.get("targets"), limit=8))
            validation = "；".join(_as_text_list(item.get("validation"), limit=3))
            tail = f" 相关标的：{targets}。" if targets else ""
            verify = f" 验证：{validation}。" if validation else ""
            lines.append(f"- {name}：{judgment}{tail}{verify}")

    priority_targets = _as_dict_list(view.get("priority_targets"), limit=4)
    if priority_targets:
        lines.append("### 优先关注")
        for item in priority_targets:
            target = _cell(item.get("target_name"))
            thesis = _short_text(str(item.get("thesis") or ""), max_len=300)
            why_now = _short_text(str(item.get("why_now") or ""), max_len=120)
            downgrade = _short_text(
                str(item.get("downgrade_trigger") or ""),
                max_len=120,
            )
            parts = [
                part
                for part in [
                    thesis,
                    f"今日增量：{why_now}" if why_now else "",
                    f"降级条件：{downgrade}" if downgrade else "",
                ]
                if part
            ]
            lines.append(f"- {target}：{' '.join(parts)}")

    baskets = _as_dict_list(view.get("baskets"), limit=4)
    if baskets:
        lines.append("### 主题篮子")
        for item in baskets:
            theme = _cell(item.get("theme"))
            judgment = _short_text(str(item.get("judgment") or ""), max_len=220)
            targets = "、".join(_as_text_list(item.get("targets"), limit=8))
            differences = _short_text(str(item.get("differences") or ""), max_len=180)
            validation = "；".join(_as_text_list(item.get("validation"), limit=3))
            risks = "；".join(_as_text_list(item.get("risks"), limit=3))
            lines.append(f"- {theme}：{judgment}")
            if targets:
                lines.append(f"  - 标的：{targets}")
            if differences:
                lines.append(f"  - 分工：{differences}")
            if validation:
                lines.append(f"  - 验证：{validation}")
            if risks:
                lines.append(f"  - 风险：{risks}")

    watchlist = _as_dict_list(view.get("watchlist"), limit=6)
    if watchlist:
        lines.append("### 待验证观察")
        for item in watchlist:
            target = _cell(item.get("target_name"))
            reason = _short_text(str(item.get("reason") or ""), max_len=160)
            needed = _short_text(str(item.get("needed_evidence") or ""), max_len=160)
            suffix = f"；升级需要：{needed}" if needed else ""
            lines.append(f"- {target}：{reason}{suffix}")

    return lines


def _render_markdown(payload: dict[str, Any]) -> str:
    report_time = datetime.fromisoformat(str(payload["report_time"]))
    lines = [f"# 盘中投研快报 {report_time.strftime('%H:%M')}", ""]

    candidates = payload["candidate_trades"]
    lines.append("## 结论")
    if candidates:
        for item in candidates[:3]:
            why = "、".join(item["why_selected"])
            lines.append(
                f"- {item['target_name']}：{_primary_clue(item)}；"
                f"{why}（score={item['score']}）"
            )
    else:
        lines.append("- 本轮暂无新增可交易个股机会。")

    if candidates:
        lines.extend(["", "## 强推逻辑"])
        strategy_lines = _render_strategy_view(payload)
        if strategy_lines:
            lines.extend(strategy_lines)
        else:
            for item in candidates:
                lines.extend(_render_logic_block(item))

    theme_clues = payload["theme_clues"]
    if theme_clues:
        lines.append("")
        lines.append("## 主题/板块线索")
        for item in theme_clues:
            why = "、".join(item["why_selected"])
            reason = "；".join(
                _unique_texts(item["evidences"] or item["reasons"], limit=2)
            )
            lines.append(
                f"- [{_target_type_label(item['target_type'])}] {item['target_name']}："
                f"{why}，score={item['score']}，{reason or '-'}"
            )

    lines.extend(["", "## 新增可交易机会"])
    lines.append("| 标的 | score | confidence | 推荐人 | 核心证据 | 风险 |")
    lines.append("| --- | ---: | ---: | --- | --- | --- |")
    for item in candidates:
        senders = "、".join(item["senders"][:5])
        if len(item["senders"]) > 5:
            senders += f" 等{len(item['senders'])}人"
        clue = "；".join(_unique_texts(item["evidences"] or item["reasons"], limit=2))
        risks = "；".join(_unique_texts(item["risks"], limit=2))
        clue = clue or "-"
        risks = risks or "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(item["target_name"]),
                    _cell(item["score"]),
                    _pct(item.get("confidence")),
                    _cell(senders),
                    _cell(clue),
                    _cell(risks),
                ]
            )
            + " |"
        )
    if not candidates:
        lines.append("| - | - | - | - | 本轮无新增可交易个股 | - |")

    lines.extend(["", "## 共识增强"])
    if payload["top_consensus"]:
        for item in payload["top_consensus"]:
            senders = "、".join(item["senders"])
            lines.append(
                f"- [{_target_type_label(item['target_type'])}] {item['target_name']}："
                f"{senders}，score={item['score']}"
            )
    else:
        lines.append("- 本轮暂无多人共识。")

    lines.extend(["", "## 观点变化"])
    if payload["opinion_changes"]:
        for item in payload["opinion_changes"]:
            lines.append(
                f"- [{_update_type_label(item['update_type'])}]"
                f"[{_stance_label(item['stance'])}] "
                f"{item['sender']} -> {item['topic_key']}：{item['summary']}"
            )
    else:
        lines.append("- 本轮暂无显著观点变化。")

    lines.extend(["", "## 推荐人可信度"])
    if payload["sender_stats"]:
        for sender, stat in payload["sender_stats"].items():
            lines.append(_sender_stat_line(sender, stat))
    else:
        lines.append("- 本轮涉及推荐人暂无 30d 回测样本。")

    lines.extend(["", "## 原始线索"])
    clue_items = payload["candidate_trades"][:3] + payload["theme_clues"][:2]
    for item in clue_items:
        clue = "；".join(
            _unique_texts(item.get("evidences") or item.get("reasons") or [], limit=2)
        )
        clue = clue or "-"
        senders = "、".join(item.get("senders", [])[:3])
        lines.append(f"- {item['target_name']} / {senders}：{clue}")
    if not clue_items:
        lines.append("- 无。")

    return "\n".join(lines) + "\n"


def generate(
    date_str: str,
    window_minutes: int,
    top: int,
    json_output: bool,
    use_llm: bool = False,
    provider_name: str | None = None,
) -> None:
    """生成盘中策略快报 JSON 和 Markdown."""
    cfg = load()
    report_time = datetime.now().replace(microsecond=0)
    payload, state = _build_payload(
        cfg.storage.data_dir,
        date_str,
        window_minutes,
        top,
        report_time,
    )
    _attach_candidate_logic(payload, use_llm, provider_name)
    markdown = _render_markdown(payload)
    json_path, md_path = _save_outputs(
        cfg.storage.data_dir,
        payload["date"],
        payload,
        markdown,
        state,
    )

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": payload["date"],
                        "has_updates": payload["has_updates"],
                        "json_path": str(json_path),
                        "markdown_path": str(md_path),
                    },
                },
                ensure_ascii=False,
            )
        )
    else:
        click.echo(f"策略快报已生成: {md_path}")
        if not payload["has_updates"]:
            click.echo("本轮无新增有效机会。")
