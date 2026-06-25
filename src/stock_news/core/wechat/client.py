"""微信数据源 HTTP 客户端。

这里只负责调用微信 API 并把返回数组规范化为 WechatMessage。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stock_news.core.wechat.models import TimeWindow, WechatMessage
from stock_news.models import WechatAuthConfig

REQUEST_TIME_FMT = "%Y%m%d%H%M%S"
RESPONSE_TIME_FMT = "%Y-%m-%d %H:%M:%S"


class WechatAPIError(RuntimeError):
    """微信 API 调用失败。"""


class WechatHTTPClient:
    """基于标准库 urllib 的微信 API 客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: int,
        auth: WechatAuthConfig,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.auth = auth

    def fetch(self, source: str, window: TimeWindow) -> list[WechatMessage]:
        """拉取单个 source + window 的微信消息。"""

        query = urlencode(
            {
                "name": source,
                "starttime": window.start.strftime(REQUEST_TIME_FMT),
                "endtime": window.end.strftime(REQUEST_TIME_FMT),
            }
        )
        separator = "&" if "?" in self.base_url else "?"
        url = f"{self.base_url}{separator}{query}"
        request = Request(url, headers=self._headers(), method="GET")

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            raise WechatAPIError(f"微信 API HTTP {exc.code}") from exc
        except URLError as exc:
            raise WechatAPIError(f"微信 API 请求失败: {exc.reason}") from exc
        except TimeoutError as exc:
            raise WechatAPIError("微信 API 请求超时") from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise WechatAPIError("微信 API 响应不是合法 JSON") from exc
        if not isinstance(payload, list):
            actual_type = type(payload).__name__
            raise WechatAPIError(f"微信 API 预期返回数组，实际是 {actual_type}")

        messages: list[WechatMessage] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            message = _parse_message(source, window, item)
            if message is not None:
                messages.append(message)
        return messages

    def _headers(self) -> dict[str, str]:
        headers = dict(self.auth.headers)
        if self.auth.type == "bearer":
            headers["Authorization"] = f"Bearer {self.auth.bearer_token}"
        elif self.auth.type == "api_key":
            headers[self.auth.api_key_header] = self.auth.api_key
        return headers


def _parse_message(
    source: str,
    window: TimeWindow,
    item: dict[object, object],
) -> WechatMessage | None:
    try:
        sender = str(item["发送人"])
        message_time = datetime.strptime(str(item["时间"]), RESPONSE_TIME_FMT)
        content = str(item["内容"])
    except (KeyError, ValueError):
        return None
    if window.start.tzinfo is not None:
        message_time = message_time.replace(tzinfo=window.start.tzinfo)
    group_name = item.get("群名称")
    return WechatMessage(
        source=source,
        sender=sender,
        message_time=message_time,
        content=content,
        group_name=str(group_name) if group_name else None,
        raw=cast(dict[str, object], item),
    )
