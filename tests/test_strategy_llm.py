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
