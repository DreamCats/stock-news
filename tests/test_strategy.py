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


def _rec(
    message_id: str,
    message_time: datetime,
    target_type: str = "stock",
    target_name: str = "寒武纪",
    sender: str = "张三",
    evidence: str = "算力订单改善",
) -> Recommendation:
    return Recommendation(
        message_id=message_id,
        sender=sender,
        message_time=message_time,
        target_type=target_type,
        target_name=target_name,
        ticker="寒武纪",
        action="买入",
        strength="强",
        confidence=0.9,
        evidence=evidence,
        reasoning=evidence,
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
    assert saved["new_recommendations"][0]["target_type"] == "stock"
    assert saved["candidate_trades"][0]["ticker"] == "寒武纪"
    assert saved["candidate_trades"][0]["target_name"] == "寒武纪"
    assert saved["candidate_trades"][0]["logic"]["source"] == "template"
    markdown = strategy_md.read_text(encoding="utf-8")
    assert "盘中投研快报" in markdown
    assert "## 强推逻辑" in markdown
    assert "给老板的判断" in markdown
    assert "为什么排前" in markdown
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
    stock_rec = _rec("msg-1", now - timedelta(minutes=5))
    theme_rec = _rec(
        "msg-2",
        now - timedelta(minutes=4),
        target_type="theme",
        target_name="国产算力",
    )
    _write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [stock_rec.model_dump(mode="json"), theme_rec.model_dump(mode="json")],
    )
    _write_json(tmp_path / today / "opinions" / "opinions.json", [])
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
    assert "## 主题/板块线索" in markdown
    assert "国产算力" in markdown
    assert "[主题]" in markdown
    assert "[theme]" not in markdown
    assert "| 寒武纪 |" in markdown
    assert "| 国产算力 |" not in markdown


def test_strategy_merges_theme_clues_and_dedupes_evidence(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    stock_rec = _rec("msg-1", now - timedelta(minutes=5))
    sector_rec = _rec(
        "msg-2",
        now - timedelta(minutes=4),
        target_type="sector",
        target_name="电解铝",
        sender="李四",
        evidence="供给收缩，电解铝价格有望上行",
    )
    macro_rec = _rec(
        "msg-3",
        now - timedelta(minutes=3),
        target_type="macro",
        target_name="电解铝",
        sender="王五",
        evidence="供给收缩，电解铝价格有望上行",
    )
    _write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [
            stock_rec.model_dump(mode="json"),
            sector_rec.model_dump(mode="json"),
            macro_rec.model_dump(mode="json"),
        ],
    )
    _write_json(tmp_path / today / "opinions" / "opinions.json", [])
    _write_json(
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
    assert "样本 1，样本不足" in markdown
    assert "100.0%" not in markdown


def test_strategy_renders_opinion_labels_in_chinese(
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
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    strategy.generate("today", 20, 5, json_output=True)
    json.loads(capsys.readouterr().out)

    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "[首次提出][看多]" in markdown
    assert "[new][bullish]" not in markdown


def test_strategy_generate_can_attach_llm_logic(
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
    _write_json(tmp_path / today / "opinions" / "opinions.json", [])
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        strategy,
        "_generate_llm_logic",
        lambda payload, provider_name: {
            "寒武纪": {
                "source": "llm",
                "strong_reason": "算力订单改善带来业绩弹性，且推荐强度高。",
                "logic_chain": ["订单改善", "业绩预期上修", "市场关注提升"],
                "information_increment": "今天新增强推证据。",
                "validation_points": ["后续订单是否继续兑现"],
                "risks": ["订单不及预期"],
                "evidence_refs": ["算力订单改善"],
            }
        },
    )

    strategy.generate("today", 20, 5, json_output=True, use_llm=True)
    json.loads(capsys.readouterr().out)

    saved = json.loads(
        (tmp_path / today / "strategy" / "strategy.json").read_text(encoding="utf-8")
    )
    assert saved["logic_generation"]["source"] == "llm"
    assert saved["candidate_trades"][0]["logic"]["source"] == "llm"

    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "算力订单改善带来业绩弹性" in markdown
    assert "订单改善 → 业绩预期上修 → 市场关注提升" in markdown


def test_strategy_renders_llm_strategy_view(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    stock_rec = _rec("msg-1", now - timedelta(minutes=5), target_name="鹏鼎控股")
    basket_rec = _rec("msg-2", now - timedelta(minutes=4), target_name="鼎泰高科")
    _write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [stock_rec.model_dump(mode="json"), basket_rec.model_dump(mode="json")],
    )
    _write_json(tmp_path / today / "opinions" / "opinions.json", [])
    monkeypatch.setattr(
        strategy,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        strategy,
        "_generate_llm_logic",
        lambda payload, provider_name: (
            {
                "鹏鼎控股": {
                    "source": "llm",
                    "conviction": "强",
                    "boss_pitch": "AI PCB 主线里最优先看鹏鼎控股。",
                    "score_driver": "多人共识且证据更集中。",
                    "validation_points": ["验证订单"],
                    "risks": ["需求不及预期"],
                    "evidence_refs": ["算力订单改善"],
                }
            },
            {
                "source": "llm",
                "market_summary": "今天主线集中在 AI PCB。",
                "mainlines": [
                    {
                        "name": "AI PCB",
                        "judgment": "算力建设带动 PCB 链条扩散。",
                        "targets": ["鹏鼎控股", "鼎泰高科"],
                        "validation": ["订单兑现"],
                    }
                ],
                "priority_targets": [
                    {
                        "target_name": "鹏鼎控股",
                        "thesis": "龙头证据更集中，优先级高于篮子标的。",
                        "why_now": "本轮多人共识强化。",
                        "downgrade_trigger": "后续无订单验证。",
                    }
                ],
                "baskets": [
                    {
                        "theme": "PCB 钻针篮子",
                        "judgment": "同主题扩散，先作为篮子跟踪。",
                        "targets": ["鼎泰高科"],
                        "differences": "当前证据不足以单独区分。",
                        "validation": ["产能爬坡"],
                        "risks": ["主题退潮"],
                    }
                ],
                "watchlist": [
                    {
                        "target_name": "鼎泰高科",
                        "reason": "更像主题跟随。",
                        "needed_evidence": "补充订单或业绩验证。",
                    }
                ],
            },
        ),
    )

    strategy.generate("today", 20, 5, json_output=True, use_llm=True)
    json.loads(capsys.readouterr().out)

    markdown = (tmp_path / today / "strategy" / "strategy.md").read_text(
        encoding="utf-8"
    )
    assert "### 今日主线" in markdown
    assert "今天主线集中在 AI PCB" in markdown
    assert "### 优先关注" in markdown
    assert "龙头证据更集中" in markdown
    assert "### 主题篮子" in markdown
    assert "PCB 钻针篮子" in markdown
    assert "### 待验证观察" in markdown
    assert "更像主题跟随" in markdown


def test_strategy_removes_unsupported_numbers_from_strategy_view() -> None:
    payload = {
        "candidate_trades": [
            {"target_name": "寒武纪", "evidences": ["算力订单改善"]},
        ],
        "theme_clues": [],
        "opinion_changes": [],
        "top_consensus": [],
    }
    strategy_view, removed = strategy._sanitize_strategy_view(
        {
            "market_summary": "供给减少 90-136 万吨，算力订单改善。",
            "mainlines": [
                {
                    "name": "算力",
                    "judgment": "订单改善。",
                    "targets": ["寒武纪"],
                    "validation": ["验证订单"],
                }
            ],
            "priority_targets": [],
            "baskets": [],
            "watchlist": [],
        },
        strategy._texts_for_fact_check(payload),
    )

    assert "90-136" in removed[0]
    assert strategy_view["market_summary"] == ""
    assert strategy_view["mainlines"][0]["judgment"] == "订单改善。"


def test_strategy_generate_cli(monkeypatch) -> None:
    calls: list[tuple[str, int, int, bool, bool, str | None]] = []

    def fake_generate(
        date_str: str,
        window_minutes: int,
        top: int,
        json_output: bool,
        use_llm: bool = False,
        provider_name: str | None = None,
    ) -> None:
        calls.append(
            (date_str, window_minutes, top, json_output, use_llm, provider_name)
        )

    monkeypatch.setattr(
        strategy,
        "generate",
        fake_generate,
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
            "--with-llm",
            "--provider",
            "fast",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("2026-05-25", 30, 3, True, True, "fast")]
