from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from stock_news.commands import strategy
from tests.strategy_helpers import rec as make_rec
from tests.strategy_helpers import write_json


def test_strategy_ranks_window_cumulative_candidates_but_tracks_updates(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    oldrec = make_rec(
        "msg-old",
        now - timedelta(hours=2),
        target_name="高分标的",
        sender="高胜率推荐人",
    )
    newrec = make_rec(
        "msg-new",
        now - timedelta(minutes=5),
        target_name="新增标的",
        sender="普通推荐人",
    )
    write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [oldrec.model_dump(mode="json")],
    )
    write_json(tmp_path / today / "opinions" / "opinions.json", [])
    write_json(
        tmp_path / "backtest_summary" / "sender_stats.json",
        [
            {
                "sender": "高胜率推荐人",
                "count": 10,
                "win_rate_t5": 1,
                "avg_excess_t5": 0.2,
            }
        ],
    )
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    strategy.generate("today", 1440, 5, json_output=True)
    json.loads(capsys.readouterr().out)

    write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [oldrec.model_dump(mode="json"), newrec.model_dump(mode="json")],
    )
    strategy.generate("today", 1440, 5, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["has_updates"] is True

    saved = json.loads(
        (tmp_path / today / "strategy" / "strategy.json").read_text(encoding="utf-8")
    )
    assert [item["target_name"] for item in saved["new_recommendations"]] == [
        "新增标的"
    ]
    assert [item["target_name"] for item in saved["candidate_trades"][:2]] == [
        "高分标的",
        "新增标的",
    ]
    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "## 推荐个股" in markdown


def test_strategy_renders_sender_credibility_with_samples_and_whitelist(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    high = make_rec("msg-1", now - timedelta(minutes=5), sender="高胜率推荐人")
    low = make_rec(
        "msg-2",
        now - timedelta(minutes=4),
        target_name="白名单标的",
        sender="白名单推荐人",
    )
    write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [high.model_dump(mode="json"), low.model_dump(mode="json")],
    )
    write_json(tmp_path / today / "opinions" / "opinions.json", [])
    write_json(
        tmp_path / "backtest_summary" / "sender_stats.json",
        [
            {"sender": "高胜率推荐人", "count": 8, "win_rate_t5": 0.75},
            {"sender": "白名单推荐人", "count": 1, "win_rate_t5": 0.2},
        ],
    )
    write_json(
        tmp_path / "2026-05-20" / "backtest" / "results.json",
        [
            {
                "sender": "高胜率推荐人",
                "ticker": "寒武纪",
                "rec_date": "2026-05-20",
                "win_t5": True,
            }
        ],
    )
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=str(tmp_path)),
            strategy=SimpleNamespace(
                sender_whitelist=["白名单推荐人"],
                sender_min_count=3,
                sender_min_win_rate=0.5,
            ),
        ),
    )

    strategy.generate("today", 20, 5, json_output=True)
    json.loads(capsys.readouterr().out)

    saved = json.loads(
        (tmp_path / today / "strategy" / "strategy.json").read_text(encoding="utf-8")
    )
    assert [item["sender"] for item in saved["sender_credibility"]] == [
        "白名单推荐人",
        "高胜率推荐人",
    ]

    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "白名单推荐人（白名单）" in markdown
    assert "寒武纪(05-20)" in markdown
