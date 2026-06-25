"""Tushare 代理 HTTP 客户端。

代理不会保存 token，本客户端每次请求都把本地 token 放进 Tushare payload。
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from stock_news.core.market import StockCompany

STOCK_BASIC_FIELDS = "ts_code,symbol,name,area,industry,market,list_date,list_status"
DEFAULT_LIST_STATUSES = ("L", "D", "P")


class TushareProxyError(RuntimeError):
    """Tushare 代理调用失败。"""


class TushareProxyClient:
    """Tushare 代理客户端。"""

    def __init__(self, *, api_url: str, token: str, timeout: int = 30) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def stock_basic(
        self,
        list_statuses: tuple[str, ...] = DEFAULT_LIST_STATUSES,
    ) -> list[StockCompany]:
        """拉取股票基础信息，包含上市、退市和暂停上市状态。"""

        companies: list[StockCompany] = []
        for status in list_statuses:
            result = self.query(
                "stock_basic",
                params={"list_status": status},
                fields=STOCK_BASIC_FIELDS,
            )
            companies.extend(_stock_company_from_row(item, status) for item in result)
        return companies

    def query(
        self,
        api_name: str,
        *,
        params: dict[str, object] | None = None,
        fields: str = "",
    ) -> list[dict[str, object]]:
        """调用 Tushare 代理，并返回按字段名展开的行。"""

        if not self.api_url:
            raise TushareProxyError("Tushare 代理地址未配置")
        if not self.token:
            raise TushareProxyError("Tushare token 未配置")

        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": fields,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.api_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
        except HTTPError as exc:
            raise TushareProxyError(f"Tushare 代理 HTTP {exc.code}") from exc
        except URLError as exc:
            raise TushareProxyError(f"Tushare 代理请求失败: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TushareProxyError("Tushare 代理请求超时") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TushareProxyError("Tushare 代理响应不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise TushareProxyError("Tushare 代理响应必须是 JSON object")
        code = data.get("code")
        if code != 0:
            message = data.get("msg") or "Tushare 代理调用失败"
            raise TushareProxyError(str(message))
        return _parse_data_rows(data.get("data"))


def _parse_data_rows(data: object) -> list[dict[str, object]]:
    if not isinstance(data, dict):
        return []
    fields = data.get("fields")
    items = data.get("items")
    if not isinstance(fields, list) or not isinstance(items, list):
        return []

    rows: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, list):
            continue
        row: dict[str, object] = {}
        for index, field in enumerate(fields):
            if isinstance(field, str):
                row[field] = item[index] if index < len(item) else None
        rows.append(row)
    return rows


def _stock_company_from_row(
    row: dict[str, object],
    fallback_list_status: str,
) -> StockCompany:
    return StockCompany(
        ts_code=str(row.get("ts_code") or ""),
        symbol=str(row.get("symbol") or ""),
        name=str(row.get("name") or ""),
        area=str(row.get("area") or ""),
        industry=str(row.get("industry") or ""),
        market=str(row.get("market") or ""),
        list_date=str(row.get("list_date") or ""),
        list_status=str(row.get("list_status") or fallback_list_status),
    )
