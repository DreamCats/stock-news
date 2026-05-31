"""策略快报 LLM 逻辑生成与事实清洗."""

from __future__ import annotations

import json
from typing import Any

import click

from .utils import _short_text, _unique_texts


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
