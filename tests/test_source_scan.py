from __future__ import annotations

from datetime import datetime

import pytest

from stock_news.common.storage import save_messages
from stock_news.models import RawMessage
from stock_news.source.models import SourceStructureItem
from stock_news.source.seeds import scan_source_seeds
from stock_news.source.storage import save_source_structures


def _message(
    sender: str,
    message_time: datetime,
    raw_content: str,
    source: str = "个人群",
    group_name: str | None = "测试群",
) -> RawMessage:
    return RawMessage(
        source=source,
        sender=sender,
        message_time=message_time,
        raw_content=raw_content,
        group_name=group_name,
        fetch_time=message_time,
        fetch_window="20260525090000-20260525100000",
    )


def _save_structure(
    tmp_path,
    msg: RawMessage,
    anchor: str,
    modifier: str,
    novel: str,
    relation_type: str,
) -> None:
    structure = SourceStructureItem(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        group_name=msg.group_name,
        is_candidate=True,
        anchor_span=anchor,
        modifier_span=modifier,
        novel_span=novel,
        relation_type=relation_type,  # type: ignore[arg-type]
        relation_evidence=novel,
        confidence=0.9,
    )
    save_source_structures(
        str(tmp_path),
        msg.message_time.date(),
        [structure],
        {structure.message_id},
    )


def test_scan_source_seeds_detects_new_combo_as_of_time(tmp_path) -> None:
    messages = [
        _message("old-anchor", datetime(2026, 4, 20, 9, 0), "PCB 是成熟赛道"),
        _message("old-modifier", datetime(2026, 5, 10, 9, 0), "半导体化趋势"),
        _message("seed", datetime(2026, 5, 11, 9, 14), "正在半导体化的PCB"),
        _message("later", datetime(2026, 5, 11, 9, 30), "半导体化的PCB 开始扩散"),
    ]
    for msg in messages:
        save_messages(
            [msg],
            str(tmp_path),
            "个人群",
            msg.message_time.strftime("%Y%m%d%H%M%S"),
            msg.message_time.strftime("%Y%m%d%H%M%S"),
        )
    _save_structure(
        tmp_path,
        messages[2],
        anchor="PCB",
        modifier="半导体化",
        novel="半导体化的PCB",
        relation_type="A化B",
    )

    result = scan_source_seeds(
        data_dir=str(tmp_path),
        start=datetime(2026, 5, 11).date(),
        end=datetime(2026, 5, 11).date(),
        as_of_time=datetime(2026, 5, 11, 9, 20),
        lookback_days=30,
        top=10,
        max_message_chars=300,
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.signal_id == "PCB::A化B::半导体化"
    assert candidate.status == "source_seed"
    assert candidate.prior_anchor_mentions == 1
    assert candidate.prior_modifier_mentions == 1
    assert candidate.prior_exact_mentions == 0
    assert candidate.prior_combo_mentions == 0
    assert candidate.asof_mentions == 1


def test_scan_source_seeds_includes_personal_messages(tmp_path) -> None:
    messages = [
        _message("old-anchor", datetime(2026, 5, 1, 9, 0), "PCB 是成熟赛道"),
        _message(
            "private",
            datetime(2026, 5, 13, 19, 57),
            "本川智能：深度布局CIPB-PCB，AI电源领域齐头并进",
            source="个人消息",
            group_name=None,
        ),
    ]
    for msg in messages:
        save_messages(
            [msg],
            str(tmp_path),
            msg.source,
            msg.message_time.strftime("%Y%m%d%H%M%S"),
            msg.message_time.strftime("%Y%m%d%H%M%S"),
        )
    _save_structure(
        tmp_path,
        messages[1],
        anchor="PCB",
        modifier="CIPB",
        novel="CIPB-PCB",
        relation_type="prefix-anchor",
    )

    result = scan_source_seeds(
        data_dir=str(tmp_path),
        start=datetime(2026, 5, 13).date(),
        end=datetime(2026, 5, 13).date(),
        as_of_time=datetime(2026, 5, 13, 20, 0),
        lookback_days=30,
        top=10,
        max_message_chars=300,
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.signal_id == "PCB::prefix-anchor::CIPB"
    assert candidate.status == "source_seed"
    assert candidate.first.row.message.source == "个人消息"


def test_scan_source_seeds_does_not_require_hardcoded_anchor(tmp_path) -> None:
    messages = [
        _message("old-anchor", datetime(2026, 5, 1, 9, 0), "XYZ 是成熟赛道"),
        _message("seed", datetime(2026, 5, 13, 9, 30), "正在材料化的XYZ"),
    ]
    for msg in messages:
        save_messages(
            [msg],
            str(tmp_path),
            "个人群",
            msg.message_time.strftime("%Y%m%d%H%M%S"),
            msg.message_time.strftime("%Y%m%d%H%M%S"),
        )
    _save_structure(
        tmp_path,
        messages[1],
        anchor="XYZ",
        modifier="材料化",
        novel="材料化的XYZ",
        relation_type="A化B",
    )

    result = scan_source_seeds(
        data_dir=str(tmp_path),
        start=datetime(2026, 5, 13).date(),
        end=datetime(2026, 5, 13).date(),
        as_of_time=datetime(2026, 5, 13, 10, 0),
        lookback_days=30,
        top=10,
        max_message_chars=300,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].signal_id == "XYZ::A化B::材料化"


def test_scan_source_seeds_uses_llm_structure_spans(tmp_path) -> None:
    messages = [
        _message("old-anchor", datetime(2026, 5, 1, 9, 0), "AI 是成熟赛道"),
        _message("seed", datetime(2026, 5, 13, 9, 30), "AI电源开始成为新方向"),
    ]
    for msg in messages:
        save_messages(
            [msg],
            str(tmp_path),
            "个人群",
            msg.message_time.strftime("%Y%m%d%H%M%S"),
            msg.message_time.strftime("%Y%m%d%H%M%S"),
        )
    _save_structure(
        tmp_path,
        messages[1],
        anchor="AI",
        modifier="电源",
        novel="AI电源",
        relation_type="modifier-anchor",
    )

    result = scan_source_seeds(
        data_dir=str(tmp_path),
        start=datetime(2026, 5, 13).date(),
        end=datetime(2026, 5, 13).date(),
        as_of_time=datetime(2026, 5, 13, 10, 0),
        lookback_days=30,
        top=10,
        max_message_chars=300,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].signal_id == "AI::modifier-anchor::电源"


def test_scan_source_seeds_requires_structures_file(tmp_path) -> None:
    msg = _message("seed", datetime(2026, 5, 13, 9, 30), "AI电源开始成为新方向")
    save_messages(
        [msg],
        str(tmp_path),
        "个人群",
        msg.message_time.strftime("%Y%m%d%H%M%S"),
        msg.message_time.strftime("%Y%m%d%H%M%S"),
    )

    with pytest.raises(ValueError, match="缺少 structures.json"):
        scan_source_seeds(
            data_dir=str(tmp_path),
            start=datetime(2026, 5, 13).date(),
            end=datetime(2026, 5, 13).date(),
            as_of_time=datetime(2026, 5, 13, 10, 0),
            lookback_days=30,
            top=10,
            max_message_chars=300,
        )
