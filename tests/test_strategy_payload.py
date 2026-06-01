from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zipfile import ZipFile

from stock_news.commands import strategy
from stock_news.commands.strategy import excel
from stock_news.models import OpinionNode
from tests.strategy_helpers import rec as make_rec
from tests.strategy_helpers import write_json


def test_strategy_generate_writes_payload_markdown_and_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    rec = make_rec("msg-1", now - timedelta(minutes=5))
    write_json(
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
    write_json(
        tmp_path / today / "opinions" / "opinions.json",
        [opinion.model_dump(mode="json")],
    )
    write_json(
        tmp_path / "backtest_summary" / "sender_stats.json",
        [
            {
                "sender": "张三",
                "count": 8,
                "win_rate_t5": 0.75,
                "avg_ret_t5": 0.12,
                "avg_excess_t5": 0.03,
            }
        ],
    )
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        excel,
        "get_ts_code",
        lambda name: "688256.SH" if name == "寒武纪" else None,
    )

    strategy.generate("today", 20, 5, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["has_updates"] is True
    assert payload["data"]["excel_path"].endswith("strategy.xlsx")

    strategy_json = tmp_path / today / "strategy" / "strategy.json"
    strategy_md = tmp_path / today / "strategy" / "strategy.md"
    strategy_xlsx = tmp_path / today / "strategy" / "strategy.xlsx"
    state_path = tmp_path / today / "strategy" / "state.json"
    saved = json.loads(strategy_json.read_text(encoding="utf-8"))
    assert saved["new_recommendations"][0]["ticker"] == "寒武纪"
    assert saved["new_recommendations"][0]["target_type"] == "stock"
    assert saved["candidate_trades"][0]["ticker"] == "寒武纪"
    assert saved["candidate_trades"][0]["target_name"] == "寒武纪"
    assert saved["candidate_trades"][0]["logic"]["source"] == "template"
    assert saved["sender_credibility"][0]["avg_ret_t5"] == 0.12
    assert saved["sender_credibility"][0]["avg_excess_t5"] == 0.03
    markdown = strategy_md.read_text(encoding="utf-8")
    assert "盘中投研快报" in markdown
    assert "## 推荐个股" in markdown
    assert "| 标的 | Score | 推荐人 | 核心证据 |" in markdown
    assert "## 推荐人可信度" in markdown
    assert "## 强推逻辑" not in markdown
    assert "confidence" not in markdown
    assert "风险" not in markdown
    with ZipFile(strategy_xlsx) as zf:
        names = set(zf.namelist())
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "xl/worksheets/sheet3.xml" in names
        sheet1 = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        sheet2 = zf.read("xl/worksheets/sheet2.xml").decode("utf-8")
        sheet3 = zf.read("xl/worksheets/sheet3.xml").decode("utf-8")
    assert "寒武纪" in sheet1
    assert "688256.SH" in sheet1
    assert "置信度" not in sheet1
    assert "风险提示" not in sheet1
    assert "张三" in sheet2
    assert "<v>0.12</v>" in sheet2
    assert "<v>0.03</v>" in sheet2
    assert "Score = 推荐人质量分" in sheet3
    assert "最终Score" in sheet3
    assert "62.8" in sheet3
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["message_ids"] == ["msg-1"]

    strategy.generate("today", 20, 5, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["has_updates"] is False


def test_strategy_separates_stock_trades_from_theme_clues(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    stockrec = make_rec("msg-1", now - timedelta(minutes=5))
    themerec = make_rec(
        "msg-2",
        now - timedelta(minutes=4),
        target_type="theme",
        target_name="国产算力",
    )
    write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [stockrec.model_dump(mode="json"), themerec.model_dump(mode="json")],
    )
    write_json(tmp_path / today / "opinions" / "opinions.json", [])
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    strategy.generate("today", 20, 5, json_output=True)
    json.loads(capsys.readouterr().out)

    saved = json.loads(
        (tmp_path / today / "strategy" / "strategy.json").read_text(encoding="utf-8")
    )
    assert [item["target_name"] for item in saved["candidate_trades"]] == ["寒武纪"]
    assert [item["target_name"] for item in saved["theme_clues"]] == ["国产算力"]

    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "## 主题/板块线索" not in markdown
    assert "国产算力" not in markdown
    assert "| 寒武纪 |" in markdown


def test_strategy_merges_theme_clues_and_dedupes_evidence(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    stockrec = make_rec("msg-1", now - timedelta(minutes=5))
    sectorrec = make_rec(
        "msg-2",
        now - timedelta(minutes=4),
        target_type="sector",
        target_name="电解铝",
        sender="李四",
        evidence="供给收缩，电解铝价格有望上行",
    )
    macrorec = make_rec(
        "msg-3",
        now - timedelta(minutes=3),
        target_type="macro",
        target_name="电解铝",
        sender="王五",
        evidence="供给收缩，电解铝价格有望上行",
    )
    write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [
            stockrec.model_dump(mode="json"),
            sectorrec.model_dump(mode="json"),
            macrorec.model_dump(mode="json"),
        ],
    )
    write_json(tmp_path / today / "opinions" / "opinions.json", [])
    write_json(
        tmp_path / "backtest_summary" / "sender_stats.json",
        [
            {
                "sender": "张三",
                "count": 1,
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

    strategy.generate("today", 20, 5, json_output=True)
    json.loads(capsys.readouterr().out)

    saved = json.loads(
        (tmp_path / today / "strategy" / "strategy.json").read_text(encoding="utf-8")
    )
    assert len(saved["theme_clues"]) == 1
    clue = saved["theme_clues"][0]
    assert clue["target_name"] == "电解铝"
    assert clue["target_type"] == "macro/sector"
    assert clue["why_selected"] == ["2 条线索", "2 位推荐人共识"]
    assert clue["evidences"] == ["供给收缩，电解铝价格有望上行"]

    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "本轮涉及推荐人暂无满足阈值的回测样本" in markdown
    assert "100.0%" not in markdown
