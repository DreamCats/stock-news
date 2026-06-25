"""企业微信机器人渠道 provider。

支持企业微信群机器人 webhook 的文本、markdown 和文件消息。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from stock_news.core.channels.http import post_json, post_multipart
from stock_news.core.channels.models import ChannelMessage, ChannelSendResult
from stock_news.core.channels.render import message_plain_text, rich_text_to_markdown
from stock_news.models import DeliveryProviderConfig, DeliveryTargetConfig


class WeComChannelError(RuntimeError):
    """企业微信渠道发送失败。"""


class WeComChannelProvider:
    """企业微信机器人渠道 provider。"""

    def __init__(self, name: str, config: DeliveryProviderConfig) -> None:
        self.name = name
        self.config = config

    def send(
        self,
        *,
        target_name: str,
        target: DeliveryTargetConfig,
        message: ChannelMessage,
    ) -> ChannelSendResult:
        """发送一条企业微信机器人消息。"""

        if target.kind != "webhook":
            raise WeComChannelError("企业微信机器人 target 只支持 webhook")

        if message.file is not None:
            media_id = self._upload_file(message.file.path, message.file.resolved_name)
            raw = self._send({"msgtype": "file", "file": {"media_id": media_id}})
            return ChannelSendResult(
                provider=self.name,
                target=target_name,
                ok=True,
                message="sent file",
                raw=raw,
            )

        if message.rich_text is not None:
            markdown = rich_text_to_markdown(message.rich_text)
            raw = self._send({"msgtype": "markdown", "markdown": {"content": markdown}})
            return ChannelSendResult(
                provider=self.name,
                target=target_name,
                ok=True,
                message="sent markdown",
                raw=raw,
            )

        if message.markdown:
            raw = self._send(
                {"msgtype": "markdown", "markdown": {"content": message.markdown}}
            )
            return ChannelSendResult(
                provider=self.name,
                target=target_name,
                ok=True,
                message="sent markdown",
                raw=raw,
            )

        raw = self._send(
            {"msgtype": "text", "text": {"content": message_plain_text(message)}}
        )
        return ChannelSendResult(
            provider=self.name,
            target=target_name,
            ok=True,
            message="sent text",
            raw=raw,
        )

    def _send(self, payload: dict[str, object]) -> dict[str, object]:
        data = post_json(
            url=self.config.webhook_url,
            payload=payload,
            timeout=self.config.timeout,
        )
        _raise_wecom_error(data)
        return data

    def _upload_file(self, path: Path, file_name: str) -> str:
        data = post_multipart(
            url=_upload_url(self.config.webhook_url),
            fields={},
            file_field="media",
            file_path=path,
            file_name=file_name,
            timeout=self.config.timeout,
        )
        _raise_wecom_error(data)
        media_id = data.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise WeComChannelError("企业微信文件上传响应缺少 media_id")
        return media_id


def _upload_url(webhook_url: str) -> str:
    parsed = urlparse(webhook_url)
    key = parse_qs(parsed.query).get("key", [""])[0]
    if not key:
        raise WeComChannelError("企业微信 webhook_url 缺少 key")
    query = urlencode({"key": key, "type": "file"})
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/cgi-bin/webhook/upload_media",
            "",
            query,
            "",
        )
    )


def _raise_wecom_error(data: dict[str, object]) -> None:
    errcode = data.get("errcode")
    if errcode not in (0, None):
        message = data.get("errmsg") or "企业微信接口调用失败"
        raise WeComChannelError(str(message))
