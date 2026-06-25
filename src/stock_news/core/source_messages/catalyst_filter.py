"""催化词匹配能力。

这里只判断文本是否命中催化词，不决定后续是否过滤、去重或投递。
"""

from __future__ import annotations

import re

from stock_news.core.source_messages.models import (
    CatalystMatchResult,
    CatalystTermHit,
    CatalystTermLibrary,
    SourceMessage,
)


def contains_term(content: str, term: str) -> bool:
    """判断正文是否包含催化词，英文和数字词使用边界匹配。"""

    stripped = term.strip()
    if not stripped:
        return False
    if stripped.isascii() and any(char.isalnum() for char in stripped):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(stripped)}(?![A-Za-z0-9])"
        return re.search(pattern, content, flags=re.IGNORECASE) is not None
    return stripped.lower() in content.lower()


def match_catalysts(
    message: SourceMessage,
    library: CatalystTermLibrary,
) -> CatalystMatchResult:
    """匹配单条消息的催化词。"""

    hits: list[CatalystTermHit] = []
    seen: set[tuple[str, str]] = set()
    for category in library.categories:
        for term in category.terms:
            if not contains_term(message.content, term):
                continue
            key = (category.id, term)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                CatalystTermHit(
                    category_id=category.id,
                    category_name=category.name,
                    color=category.color,
                    term=term,
                )
            )
    return CatalystMatchResult(message=message, hits=tuple(hits))


def match_catalyst_messages(
    messages: list[SourceMessage],
    library: CatalystTermLibrary,
) -> list[CatalystMatchResult]:
    """批量匹配消息，保留未命中的结果。"""

    return [match_catalysts(message, library) for message in messages]


def filter_catalyst_messages(
    messages: list[SourceMessage],
    library: CatalystTermLibrary,
) -> list[CatalystMatchResult]:
    """批量匹配消息，只返回命中催化词的结果。"""

    return [
        result
        for result in match_catalyst_messages(messages, library)
        if result.has_hit
    ]
