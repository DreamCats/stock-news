from __future__ import annotations

from datetime import date

import pytest
from click import ClickException

from stock_news.commands import fetch


class FixedDate(date):
    @classmethod
    def today(cls) -> FixedDate:
        return cls(2026, 5, 25)


def test_resolve_fetch_window_with_explicit_date_time_range() -> None:
    start, end = fetch.resolve_fetch_window(
        None,
        None,
        None,
        "2026-05-25",
        "09:00-23:00",
    )

    assert start == "20260525090000"
    assert end == "20260525230000"


def test_resolve_fetch_window_today_is_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "date", FixedDate)

    start, end = fetch.resolve_fetch_window(
        None,
        None,
        None,
        "today",
        "09:00-23:00",
    )

    assert start == "20260525090000"
    assert end == "20260525230000"


def test_resolve_fetch_window_rejects_mixed_modes() -> None:
    with pytest.raises(ClickException):
        fetch.resolve_fetch_window(
            "20260525090000",
            "20260525230000",
            None,
            "today",
            "09:00-23:00",
        )
