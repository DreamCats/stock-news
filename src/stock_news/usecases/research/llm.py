"""公开研究源每日摘要 LLM 调用。

这里把近 48 小时抓到的公开研究内容压成 JSON 证据，让模型用中文总结主线和重点文章。
"""

from __future__ import annotations

import json
import re
from typing import Any

from stock_news.core.llm import LLMClient, LLMClientError
from stock_news.models import LLMConfig
from stock_news.usecases.research.models import (
    ResearchBriefDocument,
    ResearchBriefItem,
    ResearchBriefSummary,
    ResearchBriefTheme,
)

_SYSTEM_PROMPT = (
    "你是A股和美股AI产业链投研编辑，负责把海外投行公开研究内容转成中文晨会/晚会摘要。"
    "你只能使用输入 documents 中的证据，不允许编造未出现的报告、观点、数字或公司。"
    "输出必须是合法 JSON，不要输出 Markdown。"
)


def summarize_research_documents(
    *,
    llm_config: LLMConfig,
    documents: list[ResearchBriefDocument],
    provider: str,
    thinking_enabled: bool,
    thinking_budget_tokens: int | None,
    client: LLMClient | None = None,
) -> ResearchBriefSummary:
    """调用 LLM 总结当天公开研究源内容。"""

    if not documents:
        return ResearchBriefSummary(
            title="近 48 小时海外投行 AI 研究摘要",
            summary="近 48 小时没有抓到新的海外投行 AI 相关公开研究内容。",
            themes=(),
            items=(),
        )

    llm_client = client or LLMClient(llm_config)
    overrides: dict[str, object] = {"thinking_enabled": thinking_enabled}
    if thinking_budget_tokens is not None:
        overrides["thinking_budget_tokens"] = thinking_budget_tokens

    result = llm_client.chat_text(
        _build_prompt(documents),
        system=_SYSTEM_PROMPT,
        provider=provider,
        provider_overrides=overrides,
    )
    return _parse_summary(result.content, documents)


def _build_prompt(documents: list[ResearchBriefDocument]) -> str:
    payload = {
        "task": "总结近48小时抓到的高盛、花旗、摩根大通、摩根士丹利公开AI研究内容",
        "requirements": [
            "用中文输出",
            (
                "summary 写成 1 段 180-300 字的中文总述，覆盖核心结论、"
                "分歧、产业链影响和后续观察点"
            ),
            (
                "themes 提炼 3-6 条主线，每条 60-120 字，"
                "说清楚为什么重要、影响哪些资产或产业链环节"
            ),
            "items 选出最值得看的文章或报告，按重要性排序",
            "每个 item 的 reason 写 80-160 字，要重组语言，不要大段复制原文",
            (
                "每个 item 的 key_points 给 3-5 条，"
                "尽量保留原文中的关键数字、主体、约束或判断"
            ),
            "不要编造 documents 之外的信息",
        ],
        "output_schema": {
            "title": "中文标题",
            "summary": "180-300字中文总述",
            "themes": [{"name": "主线名", "description": "主线说明"}],
            "items": [
                {
                    "source_name": "来源名",
                    "title": "文章标题",
                    "url": "原文链接",
                    "published_at": "发布时间",
                    "reason": "为什么值得看",
                    "key_points": ["要点1", "要点2", "要点3"],
                }
            ],
        },
        "documents": [
            {
                "id": index,
                "source_name": item.source_name,
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at,
                "fetched_at": item.fetched_at,
                "text_excerpt": item.text_excerpt,
            }
            for index, item in enumerate(documents, start=1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_summary(
    content: str,
    documents: list[ResearchBriefDocument],
) -> ResearchBriefSummary:
    data = _parse_json_object(content)
    doc_by_url = {item.url: item for item in documents}
    themes = _parse_themes(data.get("themes"))
    items = _parse_items(data.get("items"), doc_by_url)
    title = str(data.get("title") or "近 48 小时海外投行 AI 研究摘要").strip()
    summary = str(data.get("summary") or "").strip()
    if not summary:
        summary = _fallback_summary(items, documents)
    return ResearchBriefSummary(
        title=title,
        summary=summary,
        themes=tuple(themes),
        items=tuple(items),
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMClientError("公开研究源摘要响应不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise LLMClientError("公开研究源摘要响应必须是 JSON object")
    return data


def _parse_themes(value: object) -> list[ResearchBriefTheme]:
    if not isinstance(value, list):
        return []
    themes: list[ResearchBriefTheme] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        description = str(raw.get("description") or "").strip()
        if name and description:
            themes.append(ResearchBriefTheme(name=name, description=description))
    return themes


def _parse_items(
    value: object,
    doc_by_url: dict[str, ResearchBriefDocument],
) -> list[ResearchBriefItem]:
    if not isinstance(value, list):
        return []
    items: list[ResearchBriefItem] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        doc = doc_by_url.get(url)
        if doc is None or url in seen:
            continue
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            continue
        seen.add(url)
        items.append(
            ResearchBriefItem(
                source_name=str(raw.get("source_name") or doc.source_name).strip(),
                title=str(raw.get("title") or doc.title).strip(),
                url=url,
                published_at=str(raw.get("published_at") or doc.published_at).strip(),
                reason=reason,
                key_points=_parse_key_points(raw.get("key_points")),
            )
        )
    return items


def _parse_key_points(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    points = [str(item).strip() for item in value if str(item).strip()]
    return tuple(points[:5])


def _fallback_summary(
    items: list[ResearchBriefItem],
    documents: list[ResearchBriefDocument],
) -> str:
    if items:
        names = "、".join(item.title for item in items[:3])
        return f"近 48 小时重点关注 {names} 等公开研究内容。"
    return f"近 48 小时抓到 {len(documents)} 条海外投行 AI 相关公开研究内容。"
