from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import backtest
from stock_news.models import Recommendation


def _rec(message_id: str, day: str, ticker: str = "测试股份") -> Recommendation:
    return Recommendation(
        message_id=message_id,
        sender="张三",
        message_time=datetime.fromisoformat(f"{day}T10:00:00"),
        ticker=ticker,
        action="买入",
        strength="strong",
        raw_content="测试推荐",
    )


def _write_recs(data_root, day: str, recs: list[Recommendation]) -> None:
    out_dir = data_root / day / "extracted"
    out_dir.mkdir(parents=True)
    (out_dir / "recommendations.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in recs], ensure_ascii=False),
        encoding="utf-8",
    )


def test_backtest_refresh_updates_missing_mature_windows(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    old_rec = _rec("old-1", "2026-05-20")
    complete_rec = _rec("complete-1", "2026-05-20", ticker="完整股份")
    today_rec = _rec("today-1", "2026-05-25")
    _write_recs(tmp_path, "2026-05-20", [old_rec, complete_rec])
    _write_recs(tmp_path, "2026-05-25", [today_rec])

    backtest_dir = tmp_path / "2026-05-20" / "backtest"
    backtest_dir.mkdir()
    (backtest_dir / "results.json").write_text(
        json.dumps(
            [
                {
                    "message_id": "old-1",
                    "sender": "张三",
                    "ticker": "测试股份",
                    "action": "买入",
                    "rec_date": "20260520",
                    "ret_t1": 0.01,
                    "win_t1": True,
                },
                {
                    "message_id": "complete-1",
                    "sender": "张三",
                    "ticker": "完整股份",
                    "action": "买入",
                    "rec_date": "20260520",
                    "ret_t1": 0.01,
                    "win_t1": True,
                    "ret_t2": 0.02,
                    "win_t2": True,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(backtest, "_resolve_ticker", lambda ticker: "000001.SZ")
    monkeypatch.setattr(
        backtest,
        "_mature_windows",
        lambda rec_dt, as_of: [] if rec_dt.isoformat() == "2026-05-25" else [1, 2],
    )

    calls: list[str] = []

    def fake_backtest_one(rec, ts_code, rec_date, as_of=None):
        calls.append(rec.message_id)
        return {
            "message_id": rec.message_id,
            "sender": rec.sender,
            "ticker": rec.ticker,
            "action": rec.action,
            "rec_date": rec_date,
            "ret_t1": 0.01,
            "win_t1": True,
            "ret_t2": 0.02,
            "win_t2": True,
        }

    monkeypatch.setattr(backtest, "_backtest_one", fake_backtest_one)

    backtest.run_backtest_refresh("2026-05-25", 6, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["refreshed"] == 1
    assert payload["skipped_complete"] == 1
    assert payload["pending"] == 1
    assert calls == ["old-1"]

    results = json.loads((backtest_dir / "results.json").read_text(encoding="utf-8"))
    old = next(item for item in results if item["message_id"] == "old-1")
    assert old["ret_t2"] == 0.02
    assert (backtest_dir / "sender_stats.json").exists()


def test_backtest_refresh_cli(monkeypatch) -> None:
    calls: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        backtest,
        "run_backtest_refresh",
        lambda as_of, window_days, json_output: calls.append(
            (as_of, window_days, json_output)
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "analyze",
            "backtest",
            "refresh",
            "--as-of",
            "2026-05-25",
            "--window-days",
            "6",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("2026-05-25", 6, True)]
