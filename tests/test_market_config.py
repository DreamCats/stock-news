from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from click.testing import CliRunner

from stock_news.cli import main
from stock_news.common import config as config_mod
from stock_news.common.market import tushare_client


def test_config_sets_tushare_api_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.yaml")
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["config", "set", "market.tushare_api_url", "http://39.106.190.32:4000"],
    )

    assert result.exit_code == 0
    saved = config_mod.load()
    assert saved.market.tushare_api_url == "http://39.106.190.32:4000"

    result = runner.invoke(main, ["--json", "config", "show"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["market"]["tushare_api_url"] == "http://39.106.190.32:4000"


def test_tushare_client_uses_configured_proxy_api_url(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    monkeypatch.setattr(tushare_client, "_get_token", lambda: "token")
    monkeypatch.setattr(
        tushare_client,
        "load",
        lambda: SimpleNamespace(
            market=SimpleNamespace(tushare_api_url="http://39.106.190.32:4000")
        ),
    )

    def fake_post(url: str, *, json: object, timeout: float) -> httpx.Response:
        requests.append({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [["000001.SZ", "20260529", 11.23]],
                },
            },
        )

    monkeypatch.setattr(tushare_client.httpx, "post", fake_post)

    df = tushare_client._api().daily(
        ts_code="000001.SZ", start_date="20260529", end_date="20260601"
    )

    assert df.to_dict("records") == [
        {"ts_code": "000001.SZ", "trade_date": "20260529", "close": 11.23}
    ]
    assert requests == [
        {
            "url": "http://39.106.190.32:4000",
            "json": {
                "api_name": "daily",
                "token": "token",
                "params": {
                    "ts_code": "000001.SZ",
                    "start_date": "20260529",
                    "end_date": "20260601",
                },
                "fields": "",
            },
            "timeout": 30.0,
        }
    ]
