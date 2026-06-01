from __future__ import annotations

from datetime import datetime

from stock_news.common.storage import save_messages
from stock_news.models import RawMessage
from stock_news.source.models import SourceExtractItem
from stock_news.source.scanner import scan_source_candidates
from stock_news.source.storage import save_source_extracts


def _message(sender: str, message_time: datetime, raw_content: str) -> RawMessage:
    return RawMessage(
        source="个人群",
        sender=sender,
        message_time=message_time,
        raw_content=raw_content,
        group_name="测试群",
        fetch_time=message_time,
        fetch_window="20260525090000-20260525100000",
    )


def test_scan_source_candidates_supports_recent_window_with_history(
    tmp_path,
) -> None:
    messages = [
        _message("old", datetime(2026, 5, 25, 9, 10), "#电碳协同 早盘提到一次"),
        _message("hit", datetime(2026, 5, 25, 9, 50), "#电碳协同 新概念"),
        _message("outside", datetime(2026, 5, 25, 9, 20), "#脑机协同 新概念"),
    ]
    save_messages(
        messages,
        str(tmp_path),
        "个人群",
        "20260525090000",
        "20260525100000",
    )
    extracted = [
        SourceExtractItem(
            message_id=messages[0].message_id,
            source=messages[0].source,
            sender=messages[0].sender,
            message_time=messages[0].message_time,
            group_name=messages[0].group_name,
            is_source_candidate=True,
            source_type="new_concept",
            terms=["电碳协同"],
            clean_title="电碳协同",
            confidence=0.8,
        ),
        SourceExtractItem(
            message_id=messages[1].message_id,
            source=messages[1].source,
            sender=messages[1].sender,
            message_time=messages[1].message_time,
            group_name=messages[1].group_name,
            is_source_candidate=True,
            source_type="new_concept",
            terms=["电碳协同"],
            clean_title="电碳协同",
            confidence=0.9,
        ),
        SourceExtractItem(
            message_id=messages[2].message_id,
            source=messages[2].source,
            sender=messages[2].sender,
            message_time=messages[2].message_time,
            group_name=messages[2].group_name,
            is_source_candidate=True,
            source_type="new_concept",
            terms=["脑机协同"],
            clean_title="脑机协同",
            confidence=0.9,
        ),
    ]
    save_source_extracts(
        str(tmp_path),
        datetime(2026, 5, 25).date(),
        extracted,
        {item.message_id for item in extracted},
    )

    result = scan_source_candidates(
        data_dir=str(tmp_path),
        start=datetime(2026, 5, 25).date(),
        end=datetime(2026, 5, 25).date(),
        lookahead_days=0,
        top=10,
        max_message_chars=300,
        window_start=datetime(2026, 5, 25, 9, 40),
        window_end=datetime(2026, 5, 25, 10, 0),
    )

    assert [item.term for item in result.candidates] == ["电碳协同"]
    assert result.candidates[0].previous_mentions == 1
    assert result.window_start == datetime(2026, 5, 25, 9, 40)
