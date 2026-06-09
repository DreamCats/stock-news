from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import nightly_cli
from stock_news.models import NightlyPublishConfig, Recommendation
from stock_news.signals.nightly import (
    generate_nightly_report,
    parse_datetime_expr,
    publish_nightly_html,
)
from tests.strategy_helpers import write_json


def _rec(
    message_id: str,
    message_time: datetime,
    *,
    target_name: str = "寒武纪",
    sender: str = "张三",
    target_type: str = "stock",
    action: str = "买入",
    evidence: str = "算力订单改善",
) -> Recommendation:
    return Recommendation(
        message_id=message_id,
        sender=sender,
        message_time=message_time,
        target_type=target_type,
        target_name=target_name,
        ticker=target_name,
        action=action,
        strength="强",
        confidence=0.9,
        evidence=evidence,
        reasoning=evidence,
        risk_note="短期涨幅较大",
        raw_content="敏感原文不要进入晚报",
    )


def _write_recs(tmp_path, day: str, recs: list[Recommendation]) -> None:
    write_json(
        tmp_path / day / "extracted" / "recommendations.json",
        [rec.model_dump(mode="json") for rec in recs],
    )


def _write_sender_stats(tmp_path) -> None:
    write_json(
        tmp_path / "backtest_summary" / "sender_stats.json",
        [
            {
                "sender": "张三",
                "count": 8,
                "win_rate_t5": 0.75,
                "avg_ret_t5": 0.12,
                "avg_excess_t5": 0.03,
            },
            {
                "sender": "李四",
                "count": 5,
                "win_rate_t5": 0.6,
                "avg_ret_t5": 0.08,
                "avg_excess_t5": 0.01,
            },
        ],
    )


def test_parse_datetime_expr_supports_relative_days() -> None:
    now = datetime(2026, 6, 9, 10, 0)

    assert parse_datetime_expr("today-21:00", now) == datetime(2026, 6, 9, 21, 0)
    assert parse_datetime_expr("yesterday-15:00", now) == datetime(
        2026,
        6,
        8,
        15,
        0,
    )


def test_generate_nightly_report_from_recommendations(tmp_path) -> None:
    _write_recs(
        tmp_path,
        "2026-06-08",
        [
            _rec("old", datetime(2026, 6, 8, 14, 30), target_name="旧票"),
            _rec("msg-1", datetime(2026, 6, 8, 16, 0)),
        ],
    )
    _write_recs(
        tmp_path,
        "2026-06-09",
        [
            _rec("msg-2", datetime(2026, 6, 9, 10, 0), sender="李四"),
            _rec(
                "sector-1",
                datetime(2026, 6, 9, 11, 0),
                target_name="AI算力",
                target_type="sector",
            ),
        ],
    )
    _write_sender_stats(tmp_path)

    output = generate_nightly_report(
        str(tmp_path),
        datetime(2026, 6, 8, 15, 0),
        datetime(2026, 6, 9, 21, 0),
        generated_at=datetime(2026, 6, 9, 21, 1),
    )

    assert output.payload["stats"] == {
        "recommendations": 4,
        "window_recommendations": 3,
        "window_stock_recommendations": 2,
        "candidates": 1,
        "final_items": 1,
    }
    assert output.payload["items"][0]["target_name"] == "寒武纪"
    assert output.payload["items"][0]["senders"] == ["张三", "李四"]
    assert "算力订单改善" in output.payload["items"][0]["brief"]
    html = output.html_path.read_text(encoding="utf-8")
    assert "每日投研晚报" in html
    assert "06-08 15:00 - 06-09 21:00" in html
    assert "寒武纪" in html
    assert "敏感原文不要进入晚报" not in html
    assert output.json_path.exists()


def test_nightly_report_filters_contact_and_cross_target_noise(tmp_path) -> None:
    _write_recs(
        tmp_path,
        "2026-06-09",
        [
            _rec(
                "msg-1",
                datetime(2026, 6, 9, 10, 0),
                target_name="甲股",
                evidence="目标市值100亿，绑定头部客户，订单进入交付期",
            ).model_copy(
                update={
                    "raw_content": (
                        "甲股 13912345678，弹性角度#乙股、丙股，还有很多联系人噪音"
                    ),
                }
            ),
            _rec(
                "msg-2",
                datetime(2026, 6, 9, 10, 5),
                target_name="乙股",
                evidence="涨价落地，产能满负荷",
            ),
            _rec(
                "msg-3",
                datetime(2026, 6, 9, 10, 10),
                target_name="丙股",
                evidence="核心供应商，客户认证突破",
            ),
        ],
    )
    _write_sender_stats(tmp_path)

    output = generate_nightly_report(
        str(tmp_path),
        datetime(2026, 6, 9, 9, 0),
        datetime(2026, 6, 9, 21, 0),
    )

    item = next(
        item for item in output.payload["items"] if item["target_name"] == "甲股"
    )
    assert "目标市值100亿" in item["brief"]
    assert "13912345678" not in item["brief"]
    assert "乙股" not in item["brief"]
    assert "丙股" not in item["brief"]
    assert "..." not in item["brief"]


def test_nightly_generate_cli(tmp_path, monkeypatch) -> None:
    _write_recs(
        tmp_path,
        "2026-06-09",
        [_rec("msg-1", datetime(2026, 6, 9, 10, 0))],
    )
    monkeypatch.setattr(
        nightly_cli,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "nightly",
            "generate",
            "--start",
            "2026-06-09 09:00",
            "--end",
            "2026-06-09 21:00",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["stats"]["candidates"] == 1
    assert payload["data"]["html_path"].endswith("nightly.html")


def test_publish_nightly_html_uses_year_month_path(tmp_path, monkeypatch) -> None:
    html_path = tmp_path / "nightly.html"
    html_path.write_text("<html>ok</html>", encoding="utf-8")
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        assert kwargs["env"]["SSHPASS"] == "secret"
        return Completed()

    monkeypatch.setattr(
        "stock_news.signals.nightly_report.publish.subprocess.run",
        fake_run,
    )

    output = publish_nightly_html(
        html_path,
        datetime(2026, 6, 9).date(),
        NightlyPublishConfig(
            host="39.106.190.32",
            user="root",
            password="secret",
            remote_dir="/var/www/stock-news",
            url_prefix="http://39.106.190.32/stock-news",
        ),
    )

    assert calls[0][-1] == "mkdir -p /var/www/stock-news/2026/06"
    assert (
        calls[1][-1]
        == "root@39.106.190.32:/var/www/stock-news/2026/06/nightly-2026-06-09.html"
    )
    assert output.remote_path == "/var/www/stock-news/2026/06/nightly-2026-06-09.html"
    assert (
        output.url == "http://39.106.190.32/stock-news/2026/06/nightly-2026-06-09.html"
    )
