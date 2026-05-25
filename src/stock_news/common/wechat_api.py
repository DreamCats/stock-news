"""微信 API 客户端."""

from __future__ import annotations

from datetime import datetime

import httpx

from stock_news.common.exceptions import APIError
from stock_news.models import RawMessage

TIME_FMT = "%Y%m%d%H%M%S"
RESPONSE_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def fetch_messages(
    base_url: str,
    source: str,
    start: str,
    end: str,
    timeout: int = 30,
) -> list[RawMessage]:
    """拉取微信 API 消息.

    Args:
        base_url: API 地址
        source: "个人消息" 或 "个人群"
        start: 开始时间，格式 yyyyMMddHHmmss
        end: 结束时间，格式 yyyyMMddHHmmss
        timeout: 请求超时秒数
    """
    params = {"name": source, "starttime": start, "endtime": end}
    try:
        resp = httpx.get(base_url, params=params, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise APIError(f"微信 API 请求失败: {e}") from e

    try:
        data = resp.json()
    except Exception as e:
        raise APIError(f"响应不是合法 JSON: {e}") from e

    if not isinstance(data, list):
        raise APIError(f"预期返回数组，实际返回 {type(data).__name__}")

    now = datetime.now()
    window = f"{start}-{end}"
    messages: list[RawMessage] = []

    for item in data:
        try:
            msg = RawMessage(
                source=source,
                sender=item["发送人"],
                message_time=datetime.strptime(item["时间"], RESPONSE_TIME_FMT),
                raw_content=item["内容"],
                group_name=item.get("群名称"),
                fetch_time=now,
                fetch_window=window,
            )
            messages.append(msg)
        except (KeyError, ValueError):
            continue

    return messages
