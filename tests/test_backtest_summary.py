from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from stock_news.commands import backtest


class FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(2026, 5, 25)


def _write_result(data_root, day: str, sender: str) -> None:
    out_dir = data_root / day / "backtest"
    out_dir.mkdir(parents=True)
    payload = [
        {
            "sender": sender,
            "win_t5": True,
            "ret_t5": 0.1,
            "excess_t5": 0.03,
        }
    ]
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_backtest_summary_defaults_to_recent_30_days(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_result(tmp_path, "2026-04-24", "old")
    _write_result(tmp_path, "2026-04-25", "start")
    _write_result(tmp_path, "2026-05-25", "today")
    monkeypatch.setattr(backtest, "date", FixedDate)
    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    backtest.run_backtest_summary(json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["meta"]["window_days"] == 30
    assert payload["meta"]["start_date"] == "2026-04-25"
    assert payload["meta"]["end_date"] == "2026-05-25"
    assert payload["meta"]["dates"] == ["2026-04-25", "2026-05-25"]
    assert payload["meta"]["total_records"] == 2


def test_backtest_summary_all_includes_all_dates(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_result(tmp_path, "2026-04-24", "old")
    _write_result(tmp_path, "2026-05-25", "today")
    monkeypatch.setattr(backtest, "date", FixedDate)
    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )

    backtest.run_backtest_summary(json_output=True, window_days=None)

    payload = json.loads(capsys.readouterr().out)
    assert payload["meta"]["window_days"] is None
    assert payload["meta"]["start_date"] is None
    assert payload["meta"]["end_date"] is None
    assert payload["meta"]["dates"] == ["2026-04-24", "2026-05-25"]
    assert payload["meta"]["total_records"] == 2
