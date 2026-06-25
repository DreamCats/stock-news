"""飞书渠道 provider。

支持通过飞书应用发送文本、富文本 post 和文件消息。
"""

from __future__ import annotations

import json
from pathlib import Path

from stock_news.core.channels.http import post_json, post_multipart
from stock_news.core.channels.models import ChannelMessage, ChannelSendResult
from stock_news.core.channels.render import message_plain_text, rich_text_to_feishu_post
from stock_news.models import DeliveryProviderConfig, DeliveryTargetConfig


class FeishuChannelError(RuntimeError):
    """飞书渠道发送失败。"""


class FeishuChannelProvider:
    """飞书渠道 provider。"""

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
        """发送一条飞书消息。"""

        token = self._app_token()
        if message.file is not None:
            file_key = self._upload_file(
                token, message.file.path, message.file.resolved_name
            )
            raw = self._send_message(
                token=token,
                target=target,
                msg_type="file",
                content={"file_key": file_key},
            )
            return ChannelSendResult(
                provider=self.name,
                target=target_name,
                ok=True,
                message="sent file",
                raw=raw,
            )

        if message.rich_text is not None:
            raw = self._send_message(
                token=token,
                target=target,
                msg_type="post",
                content=rich_text_to_feishu_post(message.rich_text),
            )
            return ChannelSendResult(
                provider=self.name,
                target=target_name,
                ok=True,
                message="sent post",
                raw=raw,
            )

        raw = self._send_message(
            token=token,
            target=target,
            msg_type="text",
            content={"text": message_plain_text(message)},
        )
        return ChannelSendResult(
            provider=self.name,
            target=target_name,
            ok=True,
            message="sent text",
            raw=raw,
        )

    def _app_token(self) -> str:
        data = post_json(
            url=f"{self.config.base_url.rstrip('/')}/open-apis/auth/v3/app_access_token/internal",
            payload={
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret,
            },
            timeout=self.config.timeout,
        )
        _raise_feishu_error(data)
        token = data.get("tenant_access_token") or data.get("app_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuChannelError("飞书 token 响应缺少 access token")
        return token

    def _send_message(
        self,
        *,
        token: str,
        target: DeliveryTargetConfig,
        msg_type: str,
        content: dict[str, object],
    ) -> dict[str, object]:
        receive_id_type, receive_id = _feishu_receive_id(target)
        data = post_json(
            url=(
                f"{self.config.base_url.rstrip('/')}/open-apis/im/v1/messages"
                f"?receive_id_type={receive_id_type}"
            ),
            payload={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.config.timeout,
        )
        _raise_feishu_error(data)
        return data

    def _upload_file(self, token: str, path: Path, file_name: str) -> str:
        data = post_multipart(
            url=f"{self.config.base_url.rstrip('/')}/open-apis/im/v1/files",
            fields={"file_type": "stream", "file_name": file_name},
            file_field="file",
            file_path=path,
            file_name=file_name,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.config.timeout,
        )
        _raise_feishu_error(data)
        result = data.get("data")
        if not isinstance(result, dict):
            raise FeishuChannelError("飞书文件上传响应缺少 data")
        file_key = result.get("file_key")
        if not isinstance(file_key, str) or not file_key:
            raise FeishuChannelError("飞书文件上传响应缺少 file_key")
        return file_key


def _feishu_receive_id(target: DeliveryTargetConfig) -> tuple[str, str]:
    if target.kind == "chat":
        receive_id = target.resolved_id or target.id
        if not receive_id:
            raise FeishuChannelError("飞书 chat target 缺少 chat_id")
        return "chat_id", receive_id
    if target.kind == "user":
        if target.resolved_id:
            return "open_id", target.resolved_id
        if target.id:
            return "open_id", target.id
        if target.email:
            return "email", target.email
    raise FeishuChannelError("飞书 target 只支持 user/chat")


def _raise_feishu_error(data: dict[str, object]) -> None:
    code = data.get("code")
    if code not in (0, None):
        message = data.get("msg") or data.get("message") or "飞书接口调用失败"
        raise FeishuChannelError(str(message))
