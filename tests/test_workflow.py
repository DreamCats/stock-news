from __future__ import annotations

import json
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import workflow


def test_workflow_run_defaults_to_dry_run() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--json",
            "workflow",
            "run",
            "--date",
            "2026-05-25",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["date"] == "2026-05-25"
    assert payload["window_minutes"] == 1440
    assert payload["steps"] == [
        "fetch --source all --last 1440m",
        "analyze classify --date 2026-05-25",
        "analyze extract --date 2026-05-25",
        "analyze opinion --date 2026-05-25",
        "analyze backtest refresh --as-of 2026-05-25 --window-days 30",
        "analyze backtest summary --window-days 30",
        "strategy generate --date 2026-05-25 --window-minutes 1440",
    ]


def test_workflow_dry_run_can_enable_strategy_llm() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--json",
            "workflow",
            "run",
            "--date",
            "2026-05-25",
            "--window-minutes",
            "20",
            "--strategy-llm",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert (
        "strategy generate --date 2026-05-25 --window-minutes 20 --with-llm"
        in payload["steps"]
    )


def test_workflow_execute_runs_steps_in_order(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        workflow,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        workflow,
        "run_fetch",
        lambda *args: calls.append(("fetch", args[3])),
    )
    monkeypatch.setattr(
        workflow,
        "classify",
        lambda date_str, _no_llm, _provider, _json: calls.append(
            ("classify", date_str)
        ),
    )
    monkeypatch.setattr(
        workflow,
        "extract",
        lambda date_str, _provider, _json: calls.append(("extract", date_str)),
    )
    monkeypatch.setattr(
        workflow,
        "opinion",
        lambda date_str, _provider, _json: calls.append(("opinion", date_str)),
    )
    monkeypatch.setattr(
        workflow,
        "run_backtest_refresh",
        lambda as_of, window_days, _json: calls.append(
            ("backtest_refresh", (as_of, window_days))
        ),
    )
    monkeypatch.setattr(
        workflow,
        "run_backtest_summary",
        lambda _json, top, min_count, window_days: calls.append(
            ("backtest_summary", (top, min_count, window_days))
        ),
    )

    def fake_strategy_generate(
        date_str: str,
        _window_minutes: int,
        _top: int,
        _json: bool,
        _use_llm: bool,
        _provider_name: str | None,
    ) -> None:
        calls.append(("strategy_generate", date_str))
        strategy_dir = tmp_path / date_str / "strategy"
        strategy_dir.mkdir(parents=True)
        (strategy_dir / "strategy.json").write_text(
            json.dumps({"has_updates": True}),
            encoding="utf-8",
        )
        (strategy_dir / "strategy.md").write_text("hello", encoding="utf-8")

    monkeypatch.setattr(workflow, "strategy_generate", fake_strategy_generate)

    workflow.run_workflow(
        date_str="2026-05-25",
        window_minutes=20,
        window_days=30,
        source="all",
        provider_name=None,
        delivery_target=None,
        delivery_route=None,
        send_empty=False,
        top=5,
        min_count=1,
        slice_hours=1,
        workers=4,
        strategy_llm=False,
        execute=True,
        json_output=True,
    )

    assert calls == [
        ("fetch", "20m"),
        ("classify", "2026-05-25"),
        ("extract", "2026-05-25"),
        ("opinion", "2026-05-25"),
        ("backtest_refresh", ("2026-05-25", 30)),
        ("backtest_summary", (5, 1, 30)),
        ("strategy_generate", "2026-05-25"),
    ]
    state_path = tmp_path / "2026-05-25" / "workflow" / "last_run.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["ok"] is True
    assert state["strategy"]["has_updates"] is True
    assert state["status"] == "success"


def test_workflow_treats_backtest_refresh_as_warning(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        workflow,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(workflow, "run_fetch", lambda *args: calls.append("fetch"))
    monkeypatch.setattr(
        workflow,
        "classify",
        lambda *_args: calls.append("classify"),
    )
    monkeypatch.setattr(workflow, "extract", lambda *_args: calls.append("extract"))
    monkeypatch.setattr(workflow, "opinion", lambda *_args: calls.append("opinion"))

    def fail_backtest_refresh(*_args: object) -> None:
        calls.append("backtest_refresh")
        raise RuntimeError("您的IP数量超限，最大数量为10个！")

    monkeypatch.setattr(workflow, "run_backtest_refresh", fail_backtest_refresh)
    monkeypatch.setattr(
        workflow,
        "run_backtest_summary",
        lambda *_args, **_kwargs: calls.append("backtest_summary"),
    )

    def fake_strategy_generate(
        date_str: str,
        _window_minutes: int,
        _top: int,
        _json: bool,
        _use_llm: bool,
        _provider_name: str | None,
    ) -> None:
        calls.append("strategy_generate")
        strategy_dir = tmp_path / date_str / "strategy"
        strategy_dir.mkdir(parents=True)
        (strategy_dir / "strategy.json").write_text(
            json.dumps({"has_updates": True}),
            encoding="utf-8",
        )
        (strategy_dir / "strategy.md").write_text("hello", encoding="utf-8")

    monkeypatch.setattr(workflow, "strategy_generate", fake_strategy_generate)

    workflow.run_workflow(
        date_str="2026-05-25",
        window_minutes=20,
        window_days=30,
        source="all",
        provider_name=None,
        delivery_target=None,
        delivery_route=None,
        send_empty=False,
        top=5,
        min_count=1,
        slice_hours=1,
        workers=4,
        strategy_llm=False,
        execute=True,
        json_output=True,
    )

    assert calls == [
        "fetch",
        "classify",
        "extract",
        "opinion",
        "backtest_refresh",
        "backtest_summary",
        "strategy_generate",
    ]
    state_path = tmp_path / "2026-05-25" / "workflow" / "last_run.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["ok"] is True
    assert state["status"] == "completed_with_warnings"
    assert state["warnings"] == [
        {
            "step": "backtest_refresh",
            "error": "您的IP数量超限，最大数量为10个！",
        }
    ]
    assert state["steps"][4]["required"] is False
    assert state["steps"][4]["ok"] is False


def test_workflow_required_step_failure_exits_nonzero(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        workflow,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(workflow, "run_fetch", lambda *args: calls.append("fetch"))

    def fail_classify(*_args: object) -> None:
        calls.append("classify")
        raise RuntimeError("classify failed")

    monkeypatch.setattr(workflow, "classify", fail_classify)
    monkeypatch.setattr(workflow, "extract", lambda *_args: calls.append("extract"))

    with pytest.raises(click.exceptions.Exit) as exc_info:
        workflow.run_workflow(
            date_str="2026-05-25",
            window_minutes=20,
            window_days=30,
            source="all",
            provider_name=None,
            delivery_target=None,
            delivery_route=None,
            send_empty=False,
            top=5,
            min_count=1,
            slice_hours=1,
            workers=4,
            strategy_llm=False,
            execute=True,
            json_output=True,
        )

    assert exc_info.value.exit_code == 1
    assert calls == ["fetch", "classify"]
    state_path = tmp_path / "2026-05-25" / "workflow" / "last_run.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["ok"] is False
    assert state["status"] == "failed"
    assert state["steps"][1]["required"] is True
