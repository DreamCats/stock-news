from __future__ import annotations

import hashlib
import importlib
import json
from datetime import datetime
from types import SimpleNamespace

from stock_news.models import OpinionNode, RawMessage, Recommendation

opinion_mod = importlib.import_module("stock_news.commands.analyze.opinion")


def _raw_message(content: str, minute: int) -> RawMessage:
    return RawMessage(
        source="个人消息",
        sender="张三",
        message_time=datetime(2026, 5, 25, 9, minute),
        raw_content=content,
        fetch_time=datetime(2026, 5, 25, 9, minute),
        fetch_window="20260525090000_20260525092000",
    )


def _recommendation(msg: RawMessage, ticker: str = "寒武纪") -> Recommendation:
    return Recommendation(
        message_id=msg.message_id,
        source=msg.source,
        sender=msg.sender,
        message_time=msg.message_time,
        ticker=ticker,
        action="关注",
        strength="中",
        reasoning="算力逻辑",
        raw_content=msg.raw_content,
    )


def _write_recommendations(tmp_path, recs: list[Recommendation]) -> None:
    out_dir = tmp_path / "2026-05-25" / "extracted"
    out_dir.mkdir(parents=True)
    (out_dir / "recommendations.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in recs], ensure_ascii=False),
        encoding="utf-8",
    )


def _write_raw_messages(tmp_path, messages: list[RawMessage]) -> None:
    out_dir = tmp_path / "2026-05-25" / "raw"
    out_dir.mkdir(parents=True)
    (out_dir / "个人消息_20260525090000_20260525092000.json").write_text(
        json.dumps([m.model_dump(mode="json") for m in messages], ensure_ascii=False),
        encoding="utf-8",
    )


def test_opinion_only_processes_new_recommendations(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    old_msg = _raw_message("继续看好寒武纪", 1)
    new_msg = _raw_message("寒武纪逻辑强化", 2)
    _write_raw_messages(tmp_path, [old_msg, new_msg])
    _write_recommendations(
        tmp_path,
        [_recommendation(old_msg), _recommendation(new_msg)],
    )

    opinion_id = hashlib.sha256("张三|寒武纪".encode()).hexdigest()[:12]
    old_node = OpinionNode(
        opinion_id=opinion_id,
        version=1,
        message_id=old_msg.message_id,
        sender="张三",
        topic_key="寒武纪",
        stance="bullish",
        update_type="new",
        summary="已有观点",
    )
    opinions_dir = tmp_path / "2026-05-25" / "opinions"
    opinions_dir.mkdir(parents=True)
    (opinions_dir / "opinions.json").write_text(
        json.dumps([old_node.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )

    calls: list[str] = []

    def fake_analyze(msg: RawMessage, history: str, provider_name: str | None):
        calls.append(msg.message_id)
        assert msg.message_id == new_msg.message_id
        assert "已有观点" in history
        return OpinionNode(
            opinion_id=opinion_id,
            version=1,
            message_id=msg.message_id,
            sender=msg.sender,
            topic_key="寒武纪",
            stance="bullish",
            update_type="reinforce",
            summary="新增强化",
        )

    monkeypatch.setattr(
        opinion_mod,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(opinion_mod, "_analyze_opinion", fake_analyze)

    opinion_mod.opinion("2026-05-25", provider_name=None, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["new"] == 1
    assert calls == [new_msg.message_id]

    saved = json.loads((opinions_dir / "opinions.json").read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[1]["version"] == 2
    assert saved[1]["previous_id"] == old_msg.message_id

    processed = json.loads(
        (opinions_dir / "processed_ids.json").read_text(encoding="utf-8")
    )
    assert processed == sorted([old_msg.message_id, new_msg.message_id])


def test_opinion_dedupes_recommendations_by_message_id(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    msg = _raw_message("寒武纪和中际旭创都可以关注", 1)
    _write_raw_messages(tmp_path, [msg])
    _write_recommendations(
        tmp_path,
        [
            _recommendation(msg, "寒武纪"),
            _recommendation(msg, "中际旭创"),
        ],
    )

    calls: list[str] = []

    def fake_analyze(msg: RawMessage, history: str, provider_name: str | None):
        calls.append(msg.message_id)
        return OpinionNode(
            opinion_id="op-1",
            version=1,
            message_id=msg.message_id,
            sender=msg.sender,
            topic_key="寒武纪",
            stance="bullish",
            update_type="new",
            summary="新增观点",
        )

    monkeypatch.setattr(
        opinion_mod,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(opinion_mod, "_analyze_opinion", fake_analyze)

    opinion_mod.opinion("2026-05-25", provider_name=None, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["new"] == 1
    assert calls == [msg.message_id]

    processed = json.loads(
        (tmp_path / "2026-05-25" / "opinions" / "processed_ids.json").read_text(
            encoding="utf-8"
        )
    )
    assert processed == [msg.message_id]


def test_opinion_batches_messages_by_sender(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    messages = [
        _raw_message("寒武纪逻辑强化", 1),
        _raw_message("继续看好寒武纪", 2),
        _raw_message("寒武纪订单改善", 3),
    ]
    _write_raw_messages(tmp_path, messages)
    _write_recommendations(tmp_path, [_recommendation(msg) for msg in messages])

    batch_calls: list[list[str]] = []
    single_calls: list[str] = []
    opinion_id = "op-1"

    def fake_batch(
        sender: str,
        msgs: list[RawMessage],
        history: str,
        provider_name: str | None,
    ):
        batch_calls.append([msg.message_id for msg in msgs])
        return {
            idx: OpinionNode(
                opinion_id=opinion_id,
                version=1,
                message_id=msg.message_id,
                sender=sender,
                topic_key="寒武纪",
                stance="bullish",
                update_type="reinforce",
                summary=f"观点{idx}",
            )
            for idx, msg in enumerate(msgs)
        }

    def fake_single(msg: RawMessage, history: str, provider_name: str | None):
        single_calls.append(msg.message_id)
        return None

    monkeypatch.setattr(
        opinion_mod,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(opinion_mod, "_analyze_opinion_batch", fake_batch)
    monkeypatch.setattr(opinion_mod, "_analyze_opinion", fake_single)

    opinion_mod.opinion("2026-05-25", provider_name=None, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["new"] == 3
    assert batch_calls == [[msg.message_id for msg in messages]]
    assert single_calls == []

    saved = json.loads(
        (tmp_path / "2026-05-25" / "opinions" / "opinions.json").read_text(
            encoding="utf-8"
        )
    )
    assert [item["version"] for item in saved] == [1, 2, 3]
    assert saved[1]["previous_id"] == messages[0].message_id
    assert saved[2]["previous_id"] == messages[1].message_id


def test_opinion_low_confidence_batch_result_gets_reviewed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    msg = _raw_message("寒武纪订单改善", 1)
    _write_raw_messages(tmp_path, [msg])
    _write_recommendations(tmp_path, [_recommendation(msg)])

    def fake_single(msg: RawMessage, history: str, provider_name: str | None):
        return OpinionNode(
            opinion_id="fast",
            version=1,
            message_id=msg.message_id,
            sender=msg.sender,
            topic_key="寒武纪订单",
            stance="bullish",
            update_type="new",
            summary="低置信快判",
            confidence=0.6,
            candidate_existing_topic=None,
        )

    review_calls: list[str] = []

    def fake_review(msg: RawMessage, history: str, provider_name: str | None):
        review_calls.append(msg.message_id)
        return OpinionNode(
            opinion_id="reviewed",
            version=1,
            message_id=msg.message_id,
            sender=msg.sender,
            topic_key="寒武纪",
            stance="bullish",
            update_type="supplement",
            summary="复核后承接寒武纪",
            confidence=0.9,
            candidate_existing_topic="寒武纪",
        )

    monkeypatch.setattr(
        opinion_mod,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(opinion_mod, "_analyze_opinion", fake_single)
    monkeypatch.setattr(opinion_mod, "_review_opinion", fake_review)

    opinion_mod.opinion("2026-05-25", provider_name=None, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["new"] == 1
    assert payload["data"]["reviewed"] == 1
    assert review_calls == [msg.message_id]

    saved = json.loads(
        (tmp_path / "2026-05-25" / "opinions" / "opinions.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved[0]["opinion_id"] == "reviewed"
    assert saved[0]["topic_key"] == "寒武纪"
    assert saved[0]["confidence"] == 0.9
    assert saved[0]["candidate_existing_topic"] == "寒武纪"


def test_opinion_failure_is_not_marked_processed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    msg = _raw_message("寒武纪新推荐", 1)
    _write_raw_messages(tmp_path, [msg])
    _write_recommendations(tmp_path, [_recommendation(msg)])

    def fail_analyze(msg: RawMessage, history: str, provider_name: str | None):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(
        opinion_mod,
        "load",
        lambda: SimpleNamespace(storage=SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(opinion_mod, "_analyze_opinion", fail_analyze)

    opinion_mod.opinion("2026-05-25", provider_name=None, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["failed"] == 1
    assert payload["data"]["total"] == 0

    processed_path = tmp_path / "2026-05-25" / "opinions" / "processed_ids.json"
    processed = json.loads(processed_path.read_text(encoding="utf-8"))
    assert msg.message_id not in processed
