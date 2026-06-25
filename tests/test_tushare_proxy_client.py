"""Tushare 代理客户端测试。"""

from __future__ import annotations

import json
from typing import Any

from stock_news.core.tushare import TushareProxyClient


def test_stock_basic_sends_token_and_parses_companies(monkeypatch: Any) -> None:
    captured: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            params = self.payload["params"]
            assert isinstance(params, dict)
            list_status = str(params["list_status"])
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": [
                            "ts_code",
                            "symbol",
                            "name",
                            "area",
                            "industry",
                            "market",
                            "list_date",
                            "list_status",
                        ],
                        "items": [
                            [
                                f"{list_status}00001.SZ",
                                f"{list_status}00001",
                                f"{list_status}状态股票",
                                "",
                                "",
                                "",
                                "20010827",
                                list_status,
                            ]
                        ],
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))
        captured.append({"timeout": timeout, "payload": payload})
        return FakeResponse(payload)

    monkeypatch.setattr("stock_news.core.tushare.client.urlopen", fake_urlopen)

    client = TushareProxyClient(
        api_url="https://tushare-proxy.example.com",
        token="local-token",
        timeout=11,
    )
    companies = client.stock_basic()

    assert [item["timeout"] for item in captured] == [11, 11, 11]
    assert [item["payload"]["params"] for item in captured] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]
    assert all(item["payload"]["api_name"] == "stock_basic" for item in captured)
    assert all(item["payload"]["token"] == "local-token" for item in captured)
    assert all(
        item["payload"]["fields"]
        == "ts_code,symbol,name,area,industry,market,list_date,list_status"
        for item in captured
    )
    assert [item.list_status for item in companies] == ["L", "D", "P"]
    assert companies[1].name == "D状态股票"
