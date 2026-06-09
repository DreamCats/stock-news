from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from stock_news.backtest import engine, refresh, storage, summary
from stock_news.cli import main
from stock_news.commands import backtest
from stock_news.common.market import db, tushare_client
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
    monkeypatch.setattr(engine, "resolve_ticker", lambda ticker: "000001.SZ")
    monkeypatch.setattr(
        engine,
        "mature_windows",
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

    monkeypatch.setattr(engine, "backtest_one", fake_backtest_one)

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
    monkeypatch.setattr(engine, "mature_windows", lambda rec_dt, as_of: [1])
    monkeypatch.setattr(
        engine,
        "backtest_one",
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
    monkeypatch.setattr(engine, "mature_windows", lambda rec_dt, as_of: [1])
    monkeypatch.setattr(
        engine,
        "resolve_ticker",
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

    monkeypatch.setattr(engine, "backtest_one", fake_backtest_one)

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


def test_backtest_one_marks_missing_price_window_unavailable(monkeypatch) -> None:
    rec = _rec("missing-price", "2026-05-20")

    monkeypatch.setattr(
        db,
        "get_next_n_trade_dates",
        lambda rec_dt, n: ["20260521", "20260522"],
    )
    monkeypatch.setattr(engine, "mature_windows", lambda rec_dt, as_of: [1, 2])

    def fake_fetch_daily(ts_code, start_date, end_date):
        if start_date == "20260520" and end_date == "20260520":
            return [{"trade_date": "20260520", "close": 10.0}]
        return [{"trade_date": "20260522", "close": 11.0}]

    monkeypatch.setattr(tushare_client, "fetch_daily", fake_fetch_daily)
    monkeypatch.setattr(
        tushare_client,
        "fetch_index_daily",
        lambda ts_code, start_date, end_date: [
            {"trade_date": start_date, "close": 100.0},
            {"trade_date": end_date, "close": 101.0},
        ],
    )

    result = engine.backtest_one(
        rec,
        "000001.SZ",
        "20260520",
        as_of=date(2026, 5, 25),
    )

    assert result is not None
    assert result["ret_t1"] is None
    assert result["win_t1"] is None
    assert result["unavailable_t1"] == "missing_price"
    assert result["ret_t2"] == 0.1
    assert summary.aggregate_by_sender([result])[0]["count"] == 1
    assert "win_rate_t1" not in summary.aggregate_by_sender([result])[0]


def test_backtest_refresh_checkpoints_before_later_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    recs = [_rec(f"rec-{i}", "2026-05-20", ticker=f"测试股份{i}") for i in range(3)]
    _write_recs(tmp_path, "2026-05-20", recs)

    monkeypatch.setattr(engine, "mature_windows", lambda rec_dt, as_of: [1])
    monkeypatch.setattr(
        engine,
        "resolve_ticker",
        lambda ticker: {
            "测试股份0": "000001.SZ",
            "测试股份1": "000002.SZ",
            "测试股份2": "000003.SZ",
        }[ticker],
    )

    def fake_backtest_one(rec, ts_code, rec_date, as_of=None):
        if rec.message_id == "rec-2":
            raise TimeoutError("timed out")
        return {
            "message_id": rec.message_id,
            "sender": rec.sender,
            "ticker": rec.ticker,
            "action": rec.action,
            "rec_date": rec_date,
            "ret_t1": 0.01,
            "win_t1": True,
        }

    saved: list[list[dict]] = []
    monkeypatch.setattr(engine, "backtest_one", fake_backtest_one)
    monkeypatch.setattr(
        storage,
        "save_backtest_results",
        lambda data_dir, dt, results: saved.append(list(results)),
    )

    with pytest.raises(TimeoutError):
        refresh.refresh_one_day(
            str(tmp_path),
            date(2026, 5, 20),
            date(2026, 5, 25),
            ticker_cache={},
            mature_cache={},
            checkpoint_every=2,
        )

    assert len(saved) == 1
    assert {item["message_id"] for item in saved[0]} == {"rec-0", "rec-1"}


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
    monkeypatch.setattr(engine, "mature_windows", lambda rec_dt, as_of: [1])

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

    monkeypatch.setattr(engine, "resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(engine, "backtest_one", fake_backtest_one)

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
