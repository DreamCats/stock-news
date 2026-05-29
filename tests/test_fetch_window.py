from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from click import ClickException

from stock_news.commands import fetch
from stock_news.common.storage import save_messages
from stock_news.models import RawMessage


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


def test_save_messages_splits_cross_day_window(tmp_path) -> None:
    messages = [
        RawMessage(
            source="个人消息",
            sender="sender-a",
            message_time=datetime(2026, 5, 28, 23, 58),
            raw_content="first",
            fetch_time=datetime(2026, 5, 29, 9, 30),
            fetch_window="20260528093000-20260529093000",
        ),
        RawMessage(
            source="个人消息",
            sender="sender-b",
            message_time=datetime(2026, 5, 29, 9, 1),
            raw_content="second",
            fetch_time=datetime(2026, 5, 29, 9, 30),
            fetch_window="20260528093000-20260529093000",
        ),
    ]

    new, skipped = save_messages(
        messages,
        str(tmp_path),
        "个人消息",
        "20260528093000",
        "20260529093000",
    )

    assert (new, skipped) == (2, 0)

    day_28 = (
        tmp_path / "2026-05-28" / "raw" / "个人消息_20260528093000_20260529093000.json"
    )
    day_29 = (
        tmp_path / "2026-05-29" / "raw" / "个人消息_20260528093000_20260529093000.json"
    )
    assert [item["raw_content"] for item in json.loads(day_28.read_text())] == ["first"]
    assert [item["raw_content"] for item in json.loads(day_29.read_text())] == [
        "second"
    ]
