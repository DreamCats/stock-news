from __future__ import annotations

from datetime import date, datetime

from stock_news.commands.source import _render_seed_markdown
from stock_news.models import RawMessage
from stock_news.source.models import (
    Mention,
    MessageRow,
    SourceSeedCandidate,
    SourceSeedResult,
)


def _candidate(
    index: int,
    *,
    status: str = "source_seed",
    novel_span: str | None = None,
) -> SourceSeedCandidate:
    msg = RawMessage(
        source="个人群",
        sender=f"sender-{index}",
        message_time=datetime(2026, 6, 7, 9, index),
        raw_content=f"这是一段老板不需要看的长原文 {index}" * 20,
        group_name="测试群",
        fetch_time=datetime(2026, 6, 7, 9, index),
        fetch_window="20260607090000-20260607100000",
    )
    row = MessageRow(
        date=date(2026, 6, 7),
        message=msg,
        category=None,
        recommendations=(),
        terms=(),
        triggers=(),
    )
    stocks = ("标的一", "标的二") if status == "mapped" else ()
    return SourceSeedCandidate(
        signal_id=f"{status}-{index}",
        status=status,
        anchor_span=f"锚点{index}",
        modifier_span=f"修饰{index}",
        novel_span=novel_span or f"新组合{index}",
        relation_type="modifier-anchor",
        score=1.0,
        novelty_strength=1.0,
        earliness_score=1.0,
        askability_score=1.0,
        trade_potential_score=1.0,
        first=Mention(term=novel_span or f"新组合{index}", row=row, stocks=stocks),
        prior_anchor_mentions=1,
        prior_modifier_mentions=0,
        prior_exact_mentions=0,
        prior_combo_mentions=0,
        asof_mentions=index,
        asof_groups=1,
        asof_senders=1,
        followup_groups=1 if status == "spreading_watch" else 0,
        followup_senders=2 if status == "spreading_watch" else 0,
        mapped_stocks=stocks,
    )


def _result(candidates: tuple[SourceSeedCandidate, ...]) -> SourceSeedResult:
    return SourceSeedResult(
        start=date(2026, 6, 7),
        end=date(2026, 6, 7),
        as_of_time=datetime(2026, 6, 7, 10, 0),
        window_start=None,
        window_end=None,
        lookback_days=30,
        scanned_messages=20,
        candidate_count=len(candidates),
        candidates=candidates,
    )


def test_source_markdown_is_brief_for_delivery() -> None:
    markdown = _render_seed_markdown(
        _result(
            (
                _candidate(1),
                _candidate(2),
                _candidate(3),
                _candidate(4),
                _candidate(
                    5,
                    status="spreading_watch",
                    novel_span="扩散验证组合",
                ),
            )
        )
    )

    numbered_lines = [
        line for line in markdown.splitlines() if line.startswith(("1. ", "2. ", "3. "))
    ]
    assert len(numbered_lines) == 3
    assert "扩散验证组合" in markdown
    assert "其余 2 个低优先级候选已省略。" in markdown
    assert "| # |" not in markdown
    assert "## 明细" not in markdown
    assert "长原文" not in markdown


def test_source_markdown_empty_state_is_one_sentence() -> None:
    markdown = _render_seed_markdown(_result(()))

    assert "本窗口暂时没有值得追问的新源头。" in markdown
    assert "| # |" not in markdown
    assert "## 明细" not in markdown


def test_source_markdown_uses_llm_brief(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_provider_for_task(task: str):
        captured["task"] = task
        return "fake-provider", object()

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "# 源头雷达 · 06-07 10:00\n\n1. LLM 改写后的老板版。"

    monkeypatch.setattr(
        "stock_news.common.llm.client.get_provider_for_task",
        fake_get_provider_for_task,
    )
    monkeypatch.setattr("stock_news.common.llm.client.chat", fake_chat)

    markdown = _render_seed_markdown(_result((_candidate(1),)), use_llm_brief=True)

    assert "LLM 改写后的老板版" in markdown
    assert "先问" not in markdown
    assert captured["task"] == "source_brief"
    messages = captured["messages"]
    assert isinstance(messages, list)
    prompt_text = "\n".join(str(item["content"]) for item in messages)
    assert "## 明细" in prompt_text
    assert "长原文" in prompt_text


def test_source_markdown_numbers_llm_paragraphs(monkeypatch) -> None:
    def fake_get_provider_for_task(task: str):
        return "fake-provider", object()

    def fake_chat(messages, **kwargs):
        return (
            "# 源头雷达 · 06-07 10:00\n\n**方向一**：自然段。\n\n**方向二**：自然段。"
        )

    monkeypatch.setattr(
        "stock_news.common.llm.client.get_provider_for_task",
        fake_get_provider_for_task,
    )
    monkeypatch.setattr("stock_news.common.llm.client.chat", fake_chat)

    markdown = _render_seed_markdown(_result((_candidate(1),)), use_llm_brief=True)

    assert "1. **方向一**：自然段。" in markdown
    assert "2. **方向二**：自然段。" in markdown


def test_source_markdown_falls_back_when_llm_fails(monkeypatch) -> None:
    def fake_get_provider_for_task(task: str):
        return "fake-provider", object()

    def fake_chat(messages, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "stock_news.common.llm.client.get_provider_for_task",
        fake_get_provider_for_task,
    )
    monkeypatch.setattr("stock_news.common.llm.client.chat", fake_chat)

    markdown = _render_seed_markdown(_result((_candidate(1),)), use_llm_brief=True)

    assert "先问 锚点1+修饰1 是不是新线索" in markdown
    assert "boom" not in markdown
