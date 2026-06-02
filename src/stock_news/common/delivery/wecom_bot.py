"""企业微信机器人 webhook 投递客户端."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from stock_news.common.delivery.feishu_bot import DeliveryMessage, DeliveryResult
from stock_news.models import DeliveryProviderConfig, DeliveryTargetConfig

_MARKDOWN_V2_MAX_CONTENT_CHARS = 4096


def _content_size(content: str) -> int:
    return len(content.encode("utf-8"))


def _take_prefix_by_size(content: str, limit: int) -> tuple[str, str]:
    size = 0
    end = 0
    for index, char in enumerate(content):
        char_size = _content_size(char)
        if size + char_size > limit:
            break
        size += char_size
        end = index + 1
    return content[:end], content[end:]


def _split_content(content: str, limit: int) -> list[str]:
    if _content_size(content) <= limit:
        return [content]

    chunks: list[str] = []
    current = ""
    for line in content.splitlines(keepends=True):
        while _content_size(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunk, line = _take_prefix_by_size(line, limit)
            chunks.append(chunk)
        if _content_size(current + line) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def _payload(message: DeliveryMessage) -> dict[str, Any]:
    if message.format == "text":
        return {"msgtype": "text", "text": {"content": message.text}}

    title = f"# {message.title}\n\n" if message.title else ""
    if message.format == "markdown_v2":
        return {
            "msgtype": "markdown_v2",
            "markdown_v2": {"content": title + message.text},
        }
    return {
        "msgtype": "markdown",
        "markdown": {"content": title + message.text},
    }


def _payloads(message: DeliveryMessage) -> list[dict[str, Any]]:
    if message.format != "markdown_v2":
        return [_payload(message)]

    title = f"# {message.title}\n\n" if message.title else ""
    content = title + message.text
    return [
        {"msgtype": "markdown_v2", "markdown_v2": {"content": chunk}}
        for chunk in _split_content(content, _MARKDOWN_V2_MAX_CONTENT_CHARS)
    ]


def _upload_url(webhook_url: str) -> str:
    parsed = urlparse(webhook_url)
    query = parse_qs(parsed.query)
    key = (query.get("key") or [""])[0]
    if not key:
        raise RuntimeError("企业微信 webhook 缺少 key，无法上传文件")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/cgi-bin/webhook/upload_media",
            "",
            urlencode({"key": key, "type": "file"}),
            "",
        )
    )


def _check_response(data: dict[str, Any], action: str) -> None:
    errcode = data.get("errcode")
    if errcode != 0:
        errmsg = data.get("errmsg") or "未知错误"
        raise RuntimeError(f"{action}失败: {errcode} {errmsg}")


def send_message(
    provider: DeliveryProviderConfig,
    target_name: str,
    target: DeliveryTargetConfig,
    message: DeliveryMessage,
) -> DeliveryResult:
    """通过企业微信群机器人 webhook 发送消息."""
    recipient_id = target.resolved_id or target.id or provider.webhook_url
    try:
        for payload in _payloads(message):
            resp = httpx.post(
                provider.webhook_url,
                json=payload,
                timeout=provider.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            _check_response(data, "企业微信发送")
    except Exception as exc:
        return DeliveryResult(
            target=target_name,
            recipient_type="webhook",
            recipient_id=recipient_id,
            ok=False,
            error=str(exc),
        )

    return DeliveryResult(
        target=target_name,
        recipient_type="webhook",
        recipient_id=recipient_id,
        ok=True,
    )


def upload_file(provider: DeliveryProviderConfig, file_path: Path) -> str:
    """上传企业微信群机器人文件并返回 media_id."""
    try:
        with file_path.open("rb") as f:
            resp = httpx.post(
                _upload_url(provider.webhook_url),
                files={"media": (file_path.name, f)},
                timeout=provider.timeout,
            )
        resp.raise_for_status()
        data = resp.json()
        _check_response(data, "企业微信上传文件")
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    media_id = data.get("media_id")
    if not isinstance(media_id, str) or not media_id:
        raise RuntimeError("企业微信上传文件失败: 响应缺少 media_id")
    return media_id


def send_file_message(
    provider: DeliveryProviderConfig,
    target_name: str,
    target: DeliveryTargetConfig,
    file_path: Path,
) -> DeliveryResult:
    """通过企业微信群机器人 webhook 发送文件附件."""
    recipient_id = target.resolved_id or target.id or target_name
    try:
        media_id = upload_file(provider, file_path)
        resp = httpx.post(
            provider.webhook_url,
            json={"msgtype": "file", "file": {"media_id": media_id}},
            timeout=provider.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        _check_response(data, "企业微信发送文件")
    except Exception as exc:
        return DeliveryResult(
            target=target_name,
            recipient_type="webhook",
            recipient_id=recipient_id,
            ok=False,
            error=str(exc),
        )

    return DeliveryResult(
        target=target_name,
        recipient_type="webhook",
        recipient_id=recipient_id,
        ok=True,
    )
