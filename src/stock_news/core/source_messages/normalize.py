"""源头消息文本归一化。

归一化结果主要用于去重和弱比较，不替代原文展示。
"""

from __future__ import annotations

import re

_WECHAT_DECORATIVE_TOKEN_RE = re.compile(
    r"\[(?:玫瑰|礼物|强|握手|抱拳|合十|爱心|太阳|咖啡|庆祝|鼓掌|胜利|OK|ok)\]"
)
_UNICODE_EMOJI_RE = re.compile(r"[\ufe0e\ufe0f\U0001f300-\U0001faff]")
_PUNCT_RE = re.compile(r"[，。！？!?,；;：:、…·~～_\-—=+*#@（）()\[\]【】\"'“”‘’]+")


def normalize_content(content: str) -> str:
    """去掉微信装饰、URL、空白和常见标点，生成稳定比较文本。"""

    text = _WECHAT_DECORATIVE_TOKEN_RE.sub("", content)
    text = _UNICODE_EMOJI_RE.sub("", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", "", text)
    text = _PUNCT_RE.sub("", text)
    return text.lower()
