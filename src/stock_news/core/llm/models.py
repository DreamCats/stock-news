"""LLM core 数据模型。

这里只描述最小聊天输入和输出，不绑定具体模型供应商协议。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ChatRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    """一条模型聊天消息。"""

    role: ChatRole
    content: str


@dataclass(frozen=True)
class ChatResult:
    """一次模型调用结果。"""

    provider: str
    model: str
    content: str
    raw: dict[str, Any]
