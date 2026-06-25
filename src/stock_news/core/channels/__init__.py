"""渠道发送 core 能力。

这里提供飞书和企业微信的统一发送入口，支持文本、富文本和文件消息。
"""

from stock_news.core.channels.feishu import FeishuChannelError, FeishuChannelProvider
from stock_news.core.channels.models import (
    ChannelFile,
    ChannelMessage,
    ChannelSendResult,
    RichTextContent,
    RichTextElement,
)
from stock_news.core.channels.sender import ChannelError, ChannelSender
from stock_news.core.channels.wecom import WeComChannelError, WeComChannelProvider

__all__ = [
    "ChannelError",
    "ChannelFile",
    "ChannelMessage",
    "ChannelSendResult",
    "ChannelSender",
    "FeishuChannelError",
    "FeishuChannelProvider",
    "RichTextContent",
    "RichTextElement",
    "WeComChannelError",
    "WeComChannelProvider",
]
