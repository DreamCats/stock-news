"""渠道 HTTP 工具。

这里封装 JSON POST 和 multipart 文件上传，避免依赖额外 HTTP 库。
"""

from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ChannelHTTPError(RuntimeError):
    """渠道 HTTP 请求失败。"""


def post_json(
    *,
    url: str,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    """发送 JSON POST 并解析响应。"""

    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    return _read_json(request, timeout=timeout)


def post_multipart(
    *,
    url: str,
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    file_name: str,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    """发送 multipart 文件 POST 并解析响应。"""

    boundary = f"----stock-news-{uuid.uuid4().hex}"
    body = _multipart_body(
        boundary=boundary,
        fields=fields,
        file_field=file_field,
        file_path=file_path,
        file_name=file_name,
    )
    request_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    request_headers.update(headers or {})
    request = Request(url, data=body, headers=request_headers, method="POST")
    return _read_json(request, timeout=timeout)


def _read_json(request: Request, *, timeout: float) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ChannelHTTPError(f"渠道 HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ChannelHTTPError(f"渠道请求失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ChannelHTTPError("渠道请求超时") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChannelHTTPError("渠道响应不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise ChannelHTTPError("渠道响应必须是 JSON object")
    return data


def _multipart_body(
    *,
    boundary: str,
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    file_name: str,
) -> bytes:
    lines: list[bytes] = []
    for key, value in fields.items():
        lines.extend(
            [
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="{key}"'.encode(),
                b"",
                value.encode("utf-8"),
            ]
        )

    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    lines.extend(
        [
            f"--{boundary}".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"'
            ).encode(),
            f"Content-Type: {content_type}".encode(),
            b"",
            file_path.read_bytes(),
            f"--{boundary}--".encode(),
            b"",
        ]
    )
    return b"\r\n".join(lines)
