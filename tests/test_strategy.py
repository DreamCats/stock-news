from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import strategy
from stock_news.models import OpinionNode, Recommendation


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _rec(message_id: str, message_time: datetime) -> Recommendation:
    return Recommendation(
        message_id=message_id,
        sender="张三",
        message_time=message_time,
        ticker="寒武纪",
        action="买入",
        strength="强",
        reasoning="算力订单改善",
        risk_note="短期涨幅较大",
        raw_content="寒武纪算力订单改善，关注",
    )


def test_strategy_generate_writes_payload_markdown_and_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    rec = _rec("msg-1", now - timedelta(minutes=5))
    _write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [rec.model_dump(mode="json")],
    )
    opinion = OpinionNode(
        opinion_id="op-1",
        version=1,
        message_id="msg-1",
        sender="张三",
        topic_key="寒武纪",
        stance="bullish",
        update_type="new",
        summary="首次看好寒武纪算力逻辑",
    )
    _write_json(
        tmp_path / today / "opinions" / "opinions.json",
        [opinion.model_dump(mode="json")],
    )
    _write_json(
        tmp_path / "backtest_summary" / "sender_stats.json",
        [
            {
                "sender": "张三",
                "count": 8,
                "win_rate_t5": 0.75,
                "avg_excess_t5": 0.03,
            }
        ],
    )
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    strategy.generate("today", 20, 5, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["has_updates"] is True

    strategy_json = tmp_path / today / "strategy" / "strategy.json"
    strategy_md = tmp_path / today / "strategy" / "strategy.md"
    state_path = tmp_path / today / "strategy" / "state.json"
    saved = json.loads(strategy_json.read_text(encoding="utf-8"))
    assert saved["new_recommendations"][0]["ticker"] == "寒武纪"
    assert saved["candidate_trades"][0]["ticker"] == "寒武纪"
    assert "盘中投研快报" in strategy_md.read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["message_ids"] == ["msg-1"]

    strategy.generate("today", 20, 5, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["has_updates"] is False


def test_strategy_generate_cli(monkeypatch) -> None:
    calls: list[tuple[str, int, int, bool]] = []
    monkeypatch.setattr(
        strategy,
        "generate",
        lambda date_str, window_minutes, top, json_output: calls.append(
            (date_str, window_minutes, top, json_output)
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "strategy",
            "generate",
            "--date",
            "2026-05-25",
            "--window-minutes",
            "30",
            "--top",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("2026-05-25", 30, 3, True)]
