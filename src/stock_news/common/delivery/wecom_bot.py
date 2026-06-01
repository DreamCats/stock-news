"""企业微信机器人 webhook 投递客户端."""

from __future__ import annotations

from typing import Any

import httpx

from stock_news.common.delivery.feishu_bot import DeliveryMessage, DeliveryResult
from stock_news.models import DeliveryProviderConfig, DeliveryTargetConfig


def _payload(message: DeliveryMessage) -> dict[str, Any]:
    if message.format == "text":
        return {"msgtype": "text", "text": {"content": message.text}}

    title = f"# {message.title}\n\n" if message.title else ""
    return {
        "msgtype": "markdown",
        "markdown": {"content": title + message.text},
    }


def send_message(
    provider: DeliveryProviderConfig,
    target_name: str,
    target: DeliveryTargetConfig,
    message: DeliveryMessage,
) -> DeliveryResult:
    """通过企业微信群机器人 webhook 发送消息."""
    recipient_id = target.resolved_id or target.id or provider.webhook_url
    try:
        resp = httpx.post(
            provider.webhook_url,
            json=_payload(message),
            timeout=provider.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        errcode = data.get("errcode")
        if errcode != 0:
            errmsg = data.get("errmsg") or "未知错误"
            raise RuntimeError(f"企业微信发送失败: {errcode} {errmsg}")
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
