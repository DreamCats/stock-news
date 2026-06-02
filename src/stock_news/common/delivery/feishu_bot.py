"""飞书应用机器人投递客户端."""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from stock_news.common.exceptions import APIError, ConfigError
from stock_news.models import DeliveryProviderConfig, DeliveryTargetConfig


@dataclass
class _TokenCache:
    token: str
    expires_at: datetime


_token_cache: dict[tuple[str, str], _TokenCache] = {}


@dataclass(frozen=True)
class DeliveryMessage:
    format: Literal["text", "post", "markdown", "markdown_v2"]
    text: str
    title: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    target: str
    recipient_type: Literal["chat", "user", "webhook"]
    recipient_id: str
    ok: bool
    message_id: str | None = None
    error: str | None = None


def _url(provider: DeliveryProviderConfig, path: str) -> str:
    return provider.base_url.rstrip("/") + path


def _check_response(data: dict[str, Any], action: str) -> dict[str, Any]:
    code = data.get("code", 0)
    if code != 0:
        msg = data.get("msg") or data.get("message") or "未知错误"
        raise APIError(f"{action}失败: {code} {msg}")
    inner = data.get("data")
    return inner if isinstance(inner, dict) else data


def get_tenant_access_token(
    provider_name: str, provider: DeliveryProviderConfig
) -> str:
    """获取并缓存 tenant_access_token."""
    cache_key = (provider_name, provider.app_id)
    cached = _token_cache.get(cache_key)
    if cached and cached.expires_at > datetime.now() + timedelta(minutes=5):
        return cached.token

    payload = {"app_id": provider.app_id, "app_secret": provider.app_secret}
    try:
        resp = httpx.post(
            _url(provider, "/open-apis/auth/v3/tenant_access_token/internal"),
            json=payload,
            timeout=provider.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise APIError(f"获取飞书 tenant_access_token 请求失败: {exc}") from exc
    except ValueError as exc:
        raise APIError(
            f"获取飞书 tenant_access_token 响应不是合法 JSON: {exc}"
        ) from exc

    checked = _check_response(data, "获取飞书 tenant_access_token")
    token = checked.get("tenant_access_token")
    if not isinstance(token, str) or not token:
        raise APIError("获取飞书 tenant_access_token 失败: 响应缺少 token")

    expire = checked.get("expire")
    ttl = int(expire) if isinstance(expire, int | float | str) else 7200
    _token_cache[cache_key] = _TokenCache(
        token=token,
        expires_at=datetime.now() + timedelta(seconds=max(60, ttl)),
    )
    return token


def _recipient(
    target: DeliveryTargetConfig,
) -> tuple[Literal["chat", "user"], str, str]:
    if target.kind == "chat":
        if not target.id:
            raise ConfigError("chat target 缺少 id")
        return "chat", "chat_id", target.id

    recipient_id = target.resolved_id or target.id
    if not recipient_id:
        raise ConfigError(
            "user target 尚未解析 open_id，请先使用 email/open_id 配置或运行 resolve"
        )
    return "user", "open_id", recipient_id


def _content(message: DeliveryMessage) -> tuple[str, str]:
    if message.format == "text":
        return "text", json.dumps({"text": message.text}, ensure_ascii=False)

    title = message.title or "stock-news"
    if message.format in ("markdown", "markdown_v2"):
        return "post", json.dumps(
            {
                "zh_cn": {
                    "title": title,
                    "content": [[{"tag": "md", "text": message.text}]],
                }
            },
            ensure_ascii=False,
        )

    lines = message.text.splitlines() or [message.text]
    content = [[{"tag": "text", "text": line}] for line in lines]
    return "post", json.dumps(
        {"zh_cn": {"title": title, "content": content}},
        ensure_ascii=False,
    )


def send_message(
    provider_name: str,
    provider: DeliveryProviderConfig,
    target_name: str,
    target: DeliveryTargetConfig,
    message: DeliveryMessage,
    *,
    idempotency_key: str | None = None,
) -> DeliveryResult:
    """向单个 target 发送消息."""
    recipient_type, receive_id_type, receive_id = _recipient(target)
    msg_type, content = _content(message)
    token = get_tenant_access_token(provider_name, provider)

    body: dict[str, Any] = {
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": content,
    }
    if idempotency_key:
        body["uuid"] = idempotency_key

    try:
        resp = httpx.post(
            _url(provider, "/open-apis/im/v1/messages"),
            params={"receive_id_type": receive_id_type},
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=provider.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        checked = _check_response(data, "飞书发送消息")
    except Exception as exc:
        return DeliveryResult(
            target=target_name,
            recipient_type=recipient_type,
            recipient_id=receive_id,
            ok=False,
            error=str(exc),
        )

    message_id = checked.get("message_id")
    return DeliveryResult(
        target=target_name,
        recipient_type=recipient_type,
        recipient_id=receive_id,
        ok=True,
        message_id=str(message_id) if message_id else None,
    )


def _file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".xls", ".xlsx"}:
        return "xls"
    if suffix in {".doc", ".docx"}:
        return "doc"
    if suffix in {".ppt", ".pptx"}:
        return "ppt"
    if suffix == ".pdf":
        return "pdf"
    return "stream"


def upload_file(
    provider_name: str,
    provider: DeliveryProviderConfig,
    file_path: Path,
) -> str:
    """上传飞书消息附件并返回 file_key."""
    token = get_tenant_access_token(provider_name, provider)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    try:
        with file_path.open("rb") as f:
            resp = httpx.post(
                _url(provider, "/open-apis/im/v1/files"),
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "file_type": _file_type(file_path),
                    "file_name": file_path.name,
                },
                files={"file": (file_path.name, f, mime_type)},
                timeout=provider.timeout,
            )
        resp.raise_for_status()
        data = resp.json()
        checked = _check_response(data, "飞书上传文件")
    except httpx.HTTPError as exc:
        raise APIError(f"飞书上传文件请求失败: {exc}") from exc
    except ValueError as exc:
        raise APIError(f"飞书上传文件响应不是合法 JSON: {exc}") from exc

    file_key = checked.get("file_key")
    if not isinstance(file_key, str) or not file_key:
        raise APIError("飞书上传文件失败: 响应缺少 file_key")
    return file_key


def send_file_message(
    provider_name: str,
    provider: DeliveryProviderConfig,
    target_name: str,
    target: DeliveryTargetConfig,
    file_path: Path,
    *,
    idempotency_key: str | None = None,
) -> DeliveryResult:
    """上传并向单个 target 发送文件附件."""
    recipient_type, receive_id_type, receive_id = _recipient(target)
    try:
        file_key = upload_file(provider_name, provider, file_path)
        token = get_tenant_access_token(provider_name, provider)
        body: dict[str, Any] = {
            "receive_id": receive_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
        }
        if idempotency_key:
            body["uuid"] = idempotency_key

        resp = httpx.post(
            _url(provider, "/open-apis/im/v1/messages"),
            params={"receive_id_type": receive_id_type},
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=provider.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        checked = _check_response(data, "飞书发送文件")
    except Exception as exc:
        return DeliveryResult(
            target=target_name,
            recipient_type=recipient_type,
            recipient_id=receive_id,
            ok=False,
            error=str(exc),
        )

    message_id = checked.get("message_id")
    return DeliveryResult(
        target=target_name,
        recipient_type=recipient_type,
        recipient_id=receive_id,
        ok=True,
        message_id=str(message_id) if message_id else None,
    )


def resolve_user_by_email(
    provider_name: str,
    provider: DeliveryProviderConfig,
    email: str,
) -> str:
    """通过邮箱解析 open_id."""
    token = get_tenant_access_token(provider_name, provider)
    try:
        resp = httpx.post(
            _url(provider, "/open-apis/contact/v3/users/batch_get_id"),
            params={"user_id_type": "open_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={"emails": [email]},
            timeout=provider.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise APIError(f"飞书按邮箱解析用户失败: {exc}") from exc
    except ValueError as exc:
        raise APIError(f"飞书按邮箱解析用户响应不是合法 JSON: {exc}") from exc

    checked = _check_response(data, "飞书按邮箱解析用户")
    users = checked.get("user_list")
    if not isinstance(users, list) or not users:
        raise APIError(f"未找到邮箱对应的飞书用户: {email}")
    user_id = users[0].get("user_id") if isinstance(users[0], dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise APIError(f"飞书按邮箱解析用户失败: 响应缺少 open_id ({email})")
    return user_id
