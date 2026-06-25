"""源头消息去重辅助。

这里只提供内容 hash 和一组消息的去重 key，是否合并由上层 usecase 决定。
"""

from __future__ import annotations

import hashlib

from stock_news.core.source_messages.normalize import normalize_content

_LONG_CLUSTER_MESSAGE_MIN_CHARS = 40


def content_hash(content: str) -> str:
    """返回归一化正文的稳定 hash。"""

    normalized = normalize_content(content)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def cluster_content_hash(contents: list[str]) -> str:
    """返回一组消息的顺序无关 hash。"""

    parts = sorted(content_hash(content) for content in contents)
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def cluster_dedupe_hash(contents: list[str]) -> str:
    """返回适合跨发送人合并的去重 key。"""

    if len(contents) == 1:
        return content_hash(contents[0])

    longest = max(contents, key=lambda content: len(normalize_content(content)))
    normalized = normalize_content(longest)
    if len(normalized) >= _LONG_CLUSTER_MESSAGE_MIN_CHARS:
        return content_hash(longest)
    return cluster_content_hash(contents)
