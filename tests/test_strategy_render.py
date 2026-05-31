from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import strategy
from stock_news.models import OpinionNode
from tests.strategy_helpers import rec as make_rec
from tests.strategy_helpers import write_json


def test_strategy_renders_opinion_labels_in_chinese(
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
    assert "## 推荐个股" in markdown
    assert "## 观点变化" not in markdown
    assert "[new][bullish]" not in markdown


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
