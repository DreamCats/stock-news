"""源头消息处理 core 能力。

当前提供催化词库合并、催化词匹配、文本归一化和去重 key。
"""

from stock_news.core.source_messages.builtin_terms import builtin_catalyst_library
from stock_news.core.source_messages.catalyst_filter import (
    contains_term,
    filter_catalyst_messages,
    match_catalyst_messages,
    match_catalysts,
)
from stock_news.core.source_messages.catalyst_terms import build_catalyst_library
from stock_news.core.source_messages.dedupe import (
    cluster_content_hash,
    cluster_dedupe_hash,
    content_hash,
)
from stock_news.core.source_messages.models import (
    CatalystCategory,
    CatalystMatchResult,
    CatalystTermHit,
    CatalystTermLibrary,
    SourceMessage,
)
from stock_news.core.source_messages.normalize import normalize_content

__all__ = [
    "CatalystCategory",
    "CatalystMatchResult",
    "CatalystTermHit",
    "CatalystTermLibrary",
    "SourceMessage",
    "build_catalyst_library",
    "builtin_catalyst_library",
    "cluster_content_hash",
    "cluster_dedupe_hash",
    "contains_term",
    "content_hash",
    "filter_catalyst_messages",
    "match_catalyst_messages",
    "match_catalysts",
    "normalize_content",
]
