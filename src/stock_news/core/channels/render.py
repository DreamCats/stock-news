"""渠道富文本渲染工具。

同一份富文本内容会按不同渠道转换为飞书 post 或企业微信 markdown。
"""

from __future__ import annotations

from stock_news.core.channels.models import ChannelMessage, RichTextContent


def message_plain_text(message: ChannelMessage) -> str:
    """把通用消息转换为纯文本。"""

    if message.text:
        return message.text
    if message.markdown:
        return message.markdown
    if message.rich_text is not None:
        return rich_text_to_markdown(message.rich_text)
    if message.file is not None:
        return message.file.resolved_name
    return ""


def rich_text_to_markdown(content: RichTextContent) -> str:
    """把富文本转换为 markdown。"""

    lines: list[str] = []
    if content.title:
        lines.append(f"## {content.title}")
    for paragraph in content.paragraphs:
        line = ""
        for item in paragraph:
            if item.tag == "a" and item.href:
                line += f"[{item.text}]({item.href})"
            else:
                line += item.text
        lines.append(line)
    return "\n".join(lines)


def rich_text_to_feishu_post(content: RichTextContent) -> dict[str, object]:
    """把富文本转换为飞书 post content。"""

    paragraphs: list[list[dict[str, str]]] = []
    for paragraph in content.paragraphs:
        blocks: list[dict[str, str]] = []
        for item in paragraph:
            if item.tag == "a" and item.href:
                blocks.append({"tag": "a", "text": item.text, "href": item.href})
            else:
                blocks.append({"tag": "text", "text": item.text})
        paragraphs.append(blocks)
    return {"post": {"zh_cn": {"title": content.title, "content": paragraphs}}}
