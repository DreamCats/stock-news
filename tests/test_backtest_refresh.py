from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import backtest
from stock_news.models import Recommendation


class FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(2026, 5, 25)


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


def test_backtest_date_reuses_incremental_refresh_semantics(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    rec = _rec("complete-1", "2026-05-20")
    _write_recs(tmp_path, "2026-05-20", [rec])

    backtest_dir = tmp_path / "2026-05-20" / "backtest"
    backtest_dir.mkdir()
    (backtest_dir / "results.json").write_text(
        json.dumps(
            [
                {
                    "message_id": "complete-1",
                    "sender": "张三",
                    "ticker": "测试股份",
                    "action": "买入",
                    "rec_date": "20260520",
                    "ret_t1": 0.01,
                    "win_t1": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[str] = []
    monkeypatch.setattr(backtest, "date", FixedDate)
    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(backtest, "_mature_windows", lambda rec_dt, as_of: [1])
    monkeypatch.setattr(
        backtest,
        "_backtest_one",
        lambda rec, ts_code, rec_date, as_of=None: calls.append(rec.message_id),
    )

    backtest.run_backtest("2026-05-20", json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["as_of"] == "2026-05-25"
    assert payload["skipped_complete"] == 1
    assert payload["refreshed"] == 0
    assert payload["results"] == 1
    assert calls == []


def test_backtest_refresh_keeps_multiple_tickers_from_same_message(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_recs(
        tmp_path,
        "2026-05-20",
        [
            _rec("multi-1", "2026-05-20", ticker="测试股份A"),
            _rec("multi-1", "2026-05-20", ticker="测试股份B"),
        ],
    )

    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(backtest, "_mature_windows", lambda rec_dt, as_of: [1])
    monkeypatch.setattr(
        backtest,
        "_resolve_ticker",
        lambda ticker: {"测试股份A": "000001.SZ", "测试股份B": "000002.SZ"}[ticker],
    )

    calls: list[tuple[str, str]] = []

    def fake_backtest_one(rec, ts_code, rec_date, as_of=None):
        calls.append((rec.ticker, ts_code))
        return {
            "message_id": rec.message_id,
            "ts_code": ts_code,
            "sender": rec.sender,
            "ticker": rec.ticker,
            "action": rec.action,
            "strength": rec.strength,
            "rec_date": rec_date,
            "ret_t1": 0.01,
            "win_t1": True,
        }

    monkeypatch.setattr(backtest, "_backtest_one", fake_backtest_one)

    backtest.run_backtest_refresh("2026-05-25", 6, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["refreshed"] == 2
    assert payload["skipped_complete"] == 0
    assert calls == [("测试股份A", "000001.SZ"), ("测试股份B", "000002.SZ")]

    results = json.loads(
        (tmp_path / "2026-05-20" / "backtest" / "results.json").read_text(
            encoding="utf-8"
        )
    )
    assert {(item["message_id"], item["ticker"]) for item in results} == {
        ("multi-1", "测试股份A"),
        ("multi-1", "测试股份B"),
    }


def test_backtest_refresh_reports_progress_and_caches_ticker(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_recs(
        tmp_path,
        "2026-05-20",
        [
            _rec("rec-1", "2026-05-20"),
            _rec("rec-2", "2026-05-20"),
        ],
    )

    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(backtest, "_mature_windows", lambda rec_dt, as_of: [1])

    resolved_tickers: list[str] = []

    def fake_resolve_ticker(ticker: str) -> str:
        resolved_tickers.append(ticker)
        return "000001.SZ"

    def fake_backtest_one(rec, ts_code, rec_date, as_of=None):
        return {
            "message_id": rec.message_id,
            "sender": rec.sender,
            "ticker": rec.ticker,
            "action": rec.action,
            "rec_date": rec_date,
            "ret_t1": 0.01,
            "win_t1": True,
        }

    monkeypatch.setattr(backtest, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(backtest, "_backtest_one", fake_backtest_one)

    backtest.run_backtest_refresh("2026-05-25", 6, json_output=False)

    captured = capsys.readouterr()
    assert "刷新回测: 2026-05-20 至 2026-05-25" in captured.err
    assert "[1/6] 2026-05-20 推荐 2 条" in captured.err
    assert "进度: 2/2" in captured.err
    assert "刷新完成:" in captured.out
    assert resolved_tickers == ["测试股份"]


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
