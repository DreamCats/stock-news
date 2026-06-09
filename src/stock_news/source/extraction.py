"""源头结构 LLM 抽取."""

from __future__ import annotations

import re

from stock_news.models import ClassifiedMessage, MessageCategory, RawMessage
from stock_news.source.models import SourceStructureItem

SOURCE_EXTRACT_BATCH_SIZE = 10
SOURCE_EXTRACT_MAX_WORKERS = 4
SOURCE_RELATIONS = {
    "A化B",
    "prefix-anchor",
    "modifier-anchor",
    "anchor-extension",
    "other",
}
SOURCE_CATEGORIES = {
    MessageCategory.RESEARCH.value,
    MessageCategory.EVENT.value,
}
SOURCE_CUES = (
    "新概念",
    "新方向",
    "新题材",
    "新应用",
    "新场景",
    "从0到1",
    "0到1",
    "预期差",
    "拐点",
    "突破",
    "替代",
    "瓶颈",
    "新路线",
    "新技术",
    "新工艺",
    "产业趋势",
    "商业化",
    "国产化",
    "半导体化",
)
NOISE_SUBSTRINGS = (
    "腾讯会议",
    "会议号",
    "密码",
    "报名",
    "联系人",
    "日报",
    "周报",
    "月报",
    "公告速递",
    "业绩交流",
)


def eligible_messages(
    messages: list[RawMessage],
    classified: dict[str, ClassifiedMessage],
    processed_ids: set[str],
    min_confidence: float,
    max_message_chars: int,
) -> list[RawMessage]:
    out: list[RawMessage] = []
    for msg in messages:
        if msg.message_id in processed_ids:
            continue
        if msg.source not in {"个人群", "个人消息"}:
            continue
        if len(msg.raw_content) > max_message_chars:
            continue
        item = classified.get(msg.message_id)
        if item is None:
            continue
        if item.confidence < min_confidence:
            continue
        if item.category.value not in SOURCE_CATEGORIES:
            continue
        if not looks_promising_for_source_extract(msg):
            continue
        out.append(msg)
    return out


def looks_promising_for_source_extract(msg: RawMessage) -> bool:
    text = msg.raw_content
    if any(part in text for part in NOISE_SUBSTRINGS):
        return False
    if _has_strong_structure(text):
        return True
    return any(cue in text for cue in SOURCE_CUES)


def extract_batch_by_llm(
    batch: list[tuple[int, RawMessage]],
    provider_name: str | None,
) -> dict[int, SourceStructureItem]:
    from stock_news.common.llm.client import chat_json_list, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt_messages

    if not provider_name:
        provider_name, _ = get_provider_for_task("source_extract")

    lines: list[str] = []
    idx_map: dict[int, tuple[int, RawMessage]] = {}
    for seq, (orig_idx, msg) in enumerate(batch, 1):
        lines.append(
            f"[{seq}] 来源: {msg.source}\n发送人: {msg.sender}\n{msg.raw_content[:900]}"
        )
        idx_map[seq] = (orig_idx, msg)

    messages = render_prompt_messages(
        "source_extract_batch",
        messages="\n\n".join(lines),
    )
    results = chat_json_list(
        messages,
        provider_name=provider_name,
        disable_thinking=True,
    )

    out: dict[int, SourceStructureItem] = {}
    for item in results:
        if not isinstance(item, dict) or "index" not in item:
            continue
        try:
            seq = int(str(item["index"]))
        except ValueError:
            continue
        if seq not in idx_map:
            continue
        orig_idx, msg = idx_map[seq]
        out[orig_idx] = structure_from_llm(msg, item, provider_name)
    return out


def structure_from_llm(
    msg: RawMessage,
    payload: dict[str, object],
    provider_name: str,
) -> SourceStructureItem:
    relation_type = str(payload.get("relation_type") or "other").strip()
    if relation_type not in SOURCE_RELATIONS:
        relation_type = "other"

    anchor = _clean_span(payload.get("anchor_span"))
    modifier = _clean_span(payload.get("modifier_span"))
    novel = _clean_span(payload.get("novel_span"))
    evidence = str(payload.get("relation_evidence") or "").strip()
    is_candidate = bool(payload.get("is_candidate"))

    reject_reason = payload.get("reject_reason")
    if is_candidate:
        missing = [
            name
            for name, value in (
                ("anchor_span", anchor),
                ("modifier_span", modifier),
                ("novel_span", novel),
            )
            if not _contains_span(msg.raw_content, value)
        ]
        if missing:
            is_candidate = False
            reject_reason = "span 无法回指原文: " + ",".join(missing)
    if not is_candidate:
        anchor = ""
        modifier = ""
        novel = ""
        relation_type = "other"

    return SourceStructureItem(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        group_name=msg.group_name,
        is_candidate=is_candidate,
        anchor_span=anchor,
        modifier_span=modifier,
        novel_span=novel,
        relation_type=relation_type,  # type: ignore[arg-type]
        relation_evidence=evidence if is_candidate else "",
        ask_question=str(payload.get("ask_question") or "").strip()
        if is_candidate
        else "",
        confidence=_confidence(payload.get("confidence")),
        reject_reason=str(reject_reason).strip() if reject_reason else None,
        llm_provider=provider_name,
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _contains_span(text: str, span: str) -> bool:
    if not span:
        return False
    return span in text or _normalize_text(span) in _normalize_text(text)


def _has_strong_structure(text: str) -> bool:
    compact = _normalize_text(text)
    return bool(
        re.search(
            r"[A-Za-z0-9\u4e00-\u9fff]{2,12}化的?[A-Z][A-Z0-9]{1,10}",
            compact,
        )
        or re.search(
            r"(?<![A-Za-z0-9])[A-Za-z0-9]{2,12}[-/][A-Z][A-Z0-9]{1,10}(?![A-Za-z0-9])",
            compact,
        )
    )


def _confidence(value: object, default: float = 0.5) -> float:
    try:
        score = float(str(value))
    except (TypeError, ValueError):
        return default
    return min(max(score, 0.0), 1.0)


def _clean_span(value: object, limit: int = 32) -> str:
    span = str(value or "").strip()
    span = re.sub(r"\s+", "", span)
    if len(span) > limit:
        return ""
    return span
