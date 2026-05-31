from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from stock_news.commands import strategy
from tests.strategy_helpers import rec as make_rec
from tests.strategy_helpers import write_json


def test_strategy_generate_can_attach_llm_logic(
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
    write_json(tmp_path / today / "opinions" / "opinions.json", [])
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
    assert "## 推荐个股" in markdown
    assert "算力订单改善带来业绩弹性" not in markdown


def test_strategy_renders_llm_strategy_view(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    today = date.today().isoformat()
    now = datetime.now().replace(microsecond=0)
    stockrec = make_rec("msg-1", now - timedelta(minutes=5), target_name="鹏鼎控股")
    basketrec = make_rec("msg-2", now - timedelta(minutes=4), target_name="鼎泰高科")
    write_json(
        tmp_path / today / "extracted" / "recommendations.json",
        [stockrec.model_dump(mode="json"), basketrec.model_dump(mode="json")],
    )
    write_json(tmp_path / today / "opinions" / "opinions.json", [])
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
    assert "## 推荐个股" in markdown
    assert "今天主线集中在 AI PCB" not in markdown
    assert "### 优先关注" not in markdown


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
