"""渠道发送通用模型。

这里描述跨飞书和企业微信都能理解的文本、富文本和文件消息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

RichTextTag = Literal["text", "a"]


@dataclass(frozen=True)
class RichTextElement:
    """富文本片段。"""

    text: str
    tag: RichTextTag = "text"
    href: str = ""


@dataclass(frozen=True)
class RichTextContent:
    """富文本内容。"""

    title: str = ""
    paragraphs: list[list[RichTextElement]] = field(default_factory=list)


@dataclass(frozen=True)
class ChannelFile:
    """待发送文件。"""

    path: Path
    file_name: str = ""

    @property
    def resolved_name(self) -> str:
        """返回最终发送文件名。"""

        return self.file_name or self.path.name


@dataclass(frozen=True)
class ChannelMessage:
    """通用渠道消息。"""

    text: str = ""
    markdown: str = ""
    rich_text: RichTextContent | None = None
    file: ChannelFile | None = None


@dataclass(frozen=True)
class ChannelSendResult:
    """一次渠道发送结果。"""

    provider: str
    target: str
    ok: bool
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
