from __future__ import annotations

import json

from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import backfill


def test_backfill_runs_dates_in_order(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        backfill,
        "run_fetch",
        lambda *args: calls.append(("fetch", args[4])),
    )
    monkeypatch.setattr(
        backfill,
        "classify",
        lambda date_str, _no_llm, _provider, _json: calls.append(
            ("classify", date_str)
        ),
    )
    monkeypatch.setattr(
        backfill,
        "extract",
        lambda date_str, _provider, _json: calls.append(("extract", date_str)),
    )
    monkeypatch.setattr(
        backfill,
        "opinion",
        lambda date_str, _provider, _json: calls.append(("opinion", date_str)),
    )

    backfill.run_backfill(
        days=2,
        end_date="2026-05-25",
        time_range="09:00-23:00",
        source="all",
        provider_name=None,
        slice_hours=1,
        workers=4,
        dry_run=False,
        json_output=True,
    )

    assert calls == [
        ("fetch", "2026-05-24"),
        ("classify", "2026-05-24"),
        ("extract", "2026-05-24"),
        ("opinion", "2026-05-24"),
        ("fetch", "2026-05-25"),
        ("classify", "2026-05-25"),
        ("extract", "2026-05-25"),
        ("opinion", "2026-05-25"),
    ]


def test_backfill_dry_run_cli() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--json",
            "backfill",
            "--days",
            "2",
            "--end-date",
            "2026-05-25",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["dates"] == ["2026-05-24", "2026-05-25"]
    assert payload["phases"] == ["fetch", "classify", "extract", "opinion"]
