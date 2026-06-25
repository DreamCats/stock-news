"""晚间 Top 投研逻辑 LLM 精选。

这里把本地 Top50 候选压缩成 JSON 证据，让指定模型精选 Top32 并产出强逻辑阐述。
"""

from __future__ import annotations

import json
import re
from typing import Any

from stock_news.core.llm import LLMClient, LLMClientError
from stock_news.models import LLMConfig
from stock_news.usecases.strategy_tasks.evening_top_logic.models import (
    EveningLLMSelection,
    EveningLogicItem,
    EveningTopLogicCandidate,
)

_SYSTEM_PROMPT = (
    "你是A股投研编辑，只做证据驱动的晚间复盘。"
    "你必须从候选标的中精选，不允许编造候选外的股票、事实或数据。"
    "输出必须是合法 JSON，不要输出 Markdown。"
)


def select_evening_top_logic(
    *,
    llm_config: LLMConfig,
    candidates: list[EveningTopLogicCandidate],
    final_count: int,
    provider: str,
    thinking_enabled: bool,
    thinking_budget_tokens: int | None,
    client: LLMClient | None = None,
) -> EveningLLMSelection:
    """调用 LLM 从候选里精选最终 Top 标的。"""

    desired_count = min(final_count, len(candidates))
    if desired_count == 0:
        return EveningLLMSelection(summary="今晚没有筛出明确的投研逻辑。", items=())

    llm_client = client or LLMClient(llm_config)
    overrides: dict[str, object] = {"thinking_enabled": thinking_enabled}
    if thinking_budget_tokens is not None:
        overrides["thinking_budget_tokens"] = thinking_budget_tokens

    result = llm_client.chat_text(
        _build_prompt(candidates, desired_count),
        system=_SYSTEM_PROMPT,
        provider=provider,
        provider_overrides=overrides,
    )
    data = _parse_json_object(result.content)
    summary = str(data.get("summary") or "").strip()
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise LLMClientError("晚间 Top 逻辑响应缺少 items 数组")

    items = _parse_items(raw_items, candidates)
    if len(items) < desired_count:
        items.extend(
            _select_missing_items(
                llm_client=llm_client,
                candidates=candidates,
                selected_items=items,
                missing_count=desired_count - len(items),
                provider=provider,
                provider_overrides=overrides,
            )
        )
    if len(items) < desired_count:
        raise LLMClientError(
            f"晚间 Top 逻辑响应数量不足: expect={desired_count} actual={len(items)}"
        )
    if not summary:
        summary = _fallback_summary(items[:desired_count])
    return EveningLLMSelection(
        summary=summary,
        items=tuple(
            EveningLogicItem(
                rank=index,
                candidate=item.candidate,
                title=item.title,
                reason=item.reason,
                evidence_description=item.evidence_description,
                key_catalysts=item.key_catalysts,
            )
            for index, item in enumerate(items[:desired_count], start=1)
        ),
    )


def _build_prompt(candidates: list[EveningTopLogicCandidate], count: int) -> str:
    payload = {
        "task": "从候选标的中选出今晚最值得重点看的投研逻辑",
        "final_count": count,
        "requirements": [
            "只选择 candidates 中的标的",
            "items 数组必须严格包含 final_count 个对象，不能少于 final_count",
            (
                "reason 必须是一段逻辑非常强的中文阐述，"
                "包含催化、传导链条和需要继续验证的关键点"
            ),
            "summary 用 1-2 句话概括今晚主线",
            "不要输出原始发送人姓名",
            "不要编造未在证据中出现的事实",
            "优先根据 evidence_messages 中的代表原文判断逻辑强度",
            "evidence_description 用自己的话重组证据，不要复制原文句子",
        ],
        "output_schema": {
            "summary": "1-2句中文总括",
            "items": [
                {
                    "ts_code": "候选中的 ts_code",
                    "title": "不超过24字的逻辑标题",
                    "reason": "一段强逻辑阐述",
                    "evidence_description": "用自己的话组织的证据描述",
                    "key_catalysts": ["3-5个关键催化词或证据标签"],
                }
            ],
        },
        "candidates": [
            _candidate_payload(index, item) for index, item in enumerate(candidates, 1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_refill_prompt(
    candidates: list[EveningTopLogicCandidate],
    count: int,
) -> str:
    payload = {
        "task": "从剩余候选标的中补齐晚间 Top 投研逻辑",
        "final_count": count,
        "requirements": [
            "items 数组必须严格包含 final_count 个对象",
            "只选择 candidates 中的标的",
            "evidence_description 用自己的话重组证据，不要复制原文句子",
            "不要输出原始发送人姓名",
            "不要编造未在证据中出现的事实",
        ],
        "output_schema": {
            "summary": "可以为空字符串",
            "items": [
                {
                    "ts_code": "候选中的 ts_code",
                    "title": "不超过24字的逻辑标题",
                    "reason": "一段强逻辑阐述",
                    "evidence_description": "用自己的话组织的证据描述",
                    "key_catalysts": ["3-5个关键催化词或证据标签"],
                }
            ],
        },
        "candidates": [
            _candidate_payload(index, item) for index, item in enumerate(candidates, 1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _candidate_payload(
    index: int, candidate: EveningTopLogicCandidate
) -> dict[str, Any]:
    return {
        "candidate_rank": index,
        "ts_code": candidate.stock.ts_code,
        "name": candidate.stock.name,
        "score": candidate.score,
        "message_count": candidate.message_count,
        "cluster_count": candidate.cluster_count,
        "sender_count": len(candidate.senders),
        "categories": list(candidate.category_names),
        "catalyst_terms": list(candidate.catalyst_terms)[:16],
        "first_time": _format_time(candidate.first_message_time),
        "last_time": _format_time(candidate.last_message_time),
        "message_clusters": [
            {
                "count": cluster.count,
                "sender_count": len(cluster.senders),
                "first_time": _format_time(cluster.first_message_time),
                "last_time": _format_time(cluster.last_message_time),
                "categories": list(cluster.category_names),
                "catalyst_terms": list(cluster.catalyst_terms)[:10],
                "sample": cluster.sample,
                "evidence_messages": list(cluster.evidence_messages),
            }
            for cluster in candidate.message_clusters[:5]
        ],
    }


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMClientError("晚间 Top 逻辑响应不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise LLMClientError("晚间 Top 逻辑响应必须是 JSON object")
    return data


def _parse_items(
    raw_items: list[object],
    candidates: list[EveningTopLogicCandidate],
) -> list[EveningLogicItem]:
    by_code = {item.stock.ts_code: item for item in candidates}
    by_name = {item.stock.name: item for item in candidates}
    seen: set[str] = set()
    items: list[EveningLogicItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        candidate = _match_candidate(raw, by_code, by_name)
        if candidate is None or candidate.stock.ts_code in seen:
            continue
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            continue
        seen.add(candidate.stock.ts_code)
        items.append(
            EveningLogicItem(
                rank=len(items) + 1,
                candidate=candidate,
                title=str(raw.get("title") or candidate.stock.label).strip(),
                reason=reason,
                evidence_description=_parse_evidence_description(raw, candidate),
                key_catalysts=_parse_key_catalysts(raw, candidate),
            )
        )
    return items


def _select_missing_items(
    *,
    llm_client: LLMClient,
    candidates: list[EveningTopLogicCandidate],
    selected_items: list[EveningLogicItem],
    missing_count: int,
    provider: str,
    provider_overrides: dict[str, object],
) -> list[EveningLogicItem]:
    selected_codes = {item.candidate.stock.ts_code for item in selected_items}
    remaining = [
        candidate
        for candidate in candidates
        if candidate.stock.ts_code not in selected_codes
    ]
    if not remaining or missing_count <= 0:
        return []
    result = llm_client.chat_text(
        _build_refill_prompt(remaining, min(missing_count, len(remaining))),
        system=_SYSTEM_PROMPT,
        provider=provider,
        provider_overrides=provider_overrides,
    )
    data = _parse_json_object(result.content)
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []
    return _parse_items(raw_items, remaining)[:missing_count]


def _match_candidate(
    raw: dict[str, object],
    by_code: dict[str, EveningTopLogicCandidate],
    by_name: dict[str, EveningTopLogicCandidate],
) -> EveningTopLogicCandidate | None:
    code = str(raw.get("ts_code") or raw.get("code") or "").strip()
    if code in by_code:
        return by_code[code]
    name = str(raw.get("name") or raw.get("stock") or "").strip()
    return by_name.get(name)


def _parse_evidence_description(
    raw: dict[str, object],
    candidate: EveningTopLogicCandidate,
) -> str:
    value = str(
        raw.get("evidence_description")
        or raw.get("evidence")
        or raw.get("evidence_summary")
        or ""
    ).strip()
    if value:
        return value
    terms = "、".join(candidate.catalyst_terms[:5]) or "催化词"
    categories = "、".join(candidate.category_names[:3]) or "多个类别"
    return (
        f"证据集中在 {candidate.cluster_count} 个内容簇、"
        f"{candidate.message_count} 条命中消息，"
        f"主要覆盖 {categories}，关键词包括 {terms}。"
    )


def _parse_key_catalysts(
    raw: dict[str, object],
    candidate: EveningTopLogicCandidate,
) -> tuple[str, ...]:
    value = raw.get("key_catalysts") or raw.get("catalysts")
    if isinstance(value, list):
        terms = [str(item).strip() for item in value if str(item).strip()]
        if terms:
            return tuple(dict.fromkeys(terms))
    return tuple(candidate.catalyst_terms[:5])


def _fallback_summary(items: list[EveningLogicItem]) -> str:
    names = "、".join(item.candidate.stock.name for item in items[:5])
    return (
        f"今晚催化强度靠前的线索集中在 {names} 等标的，"
        "核心是多消息簇和多催化词的交叉验证。"
    )


def _format_time(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return str(value.strftime("%H:%M"))
    return str(value)
