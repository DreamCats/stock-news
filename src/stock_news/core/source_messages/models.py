"""源头消息处理通用模型。

这里描述后续策略和 usecase 都能复用的消息、催化词分类和命中结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SourceMessage:
    """待处理的源头消息。"""

    message_id: str
    content: str
    source: str = ""
    sender: str = ""
    group_name: str | None = None
    message_time: datetime | None = None


@dataclass(frozen=True)
class CatalystCategory:
    """一个催化词分类。"""

    id: str
    name: str
    color: str
    terms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CatalystTermLibrary:
    """催化词库。"""

    version: int = 1
    categories: tuple[CatalystCategory, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CatalystTermHit:
    """一次催化词命中。"""

    category_id: str
    category_name: str
    color: str
    term: str


@dataclass(frozen=True)
class CatalystMatchResult:
    """单条消息的催化词匹配结果。"""

    message: SourceMessage
    hits: tuple[CatalystTermHit, ...] = field(default_factory=tuple)

    @property
    def has_hit(self) -> bool:
        """是否命中任意催化词。"""

        return bool(self.hits)
