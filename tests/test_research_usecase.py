"""公开研究源每日摘要用例测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from stock_news.core.aly import AlyPublishResult
from stock_news.core.channels import ChannelSendResult
from stock_news.core.research_sources import ResearchDocumentRecord, ResearchSyncSummary
from stock_news.models import AppConfig
from stock_news.usecases.research import run_research_daily_brief_task


class FakeResearchFetcher:
    """替代真实网络的研究源抓取器。"""

    def __init__(self, record: ResearchDocumentRecord) -> None:
        self.record = record
        self.sync_called = False
        self.candidate_since: datetime | None = None
        self.fetched_start: datetime | None = None
        self.fetched_end: datetime | None = None

    def sync(self, **_kwargs: object) -> ResearchSyncSummary:
        self.sync_called = True
        raw_since = _kwargs.get("candidate_since")
        if isinstance(raw_since, datetime):
            self.candidate_since = raw_since
        return ResearchSyncSummary(
            sources=4,
            candidates=1,
            fetched=1,
            inserted=1,
            updated=0,
            unchanged=0,
            skipped=0,
            failed=0,
            dry_run=False,
            errors=[],
        )

    def list_documents(self, **_kwargs: object) -> list[ResearchDocumentRecord]:
        raw_start = _kwargs.get("fetched_start")
        raw_end = _kwargs.get("fetched_end")
        if isinstance(raw_start, datetime):
            self.fetched_start = raw_start
        if isinstance(raw_end, datetime):
            self.fetched_end = raw_end
        return [self.record]


class FakeLLMClient:
    """替代真实 LLM 调用。"""

    def __init__(self) -> None:
        self.provider = ""
        self.overrides: dict[str, object] = {}

    def chat_text(
        self,
        _prompt: str,
        *,
        system: str = "",
        provider: str | None = None,
        task: str | None = None,
        provider_overrides: dict[str, object] | None = None,
    ) -> Any:
        del system, task
        self.provider = provider or ""
        self.overrides = provider_overrides or {}
        return SimpleNamespace(
            content=json.dumps(
                {
                    "title": "今晚海外投行 AI 研究摘要",
                    "summary": "AI 基建和电力约束仍是近 48 小时的核心线索。",
                    "themes": [
                        {
                            "name": "AI 基建",
                            "description": "算力扩张继续拉动数据中心和电力需求。",
                        }
                    ],
                    "items": [
                        {
                            "source_name": "高盛",
                            "title": "AI Winners",
                            "url": "https://example.com/ai",
                            "published_at": "June 25, 2026",
                            "reason": "文章把 AI 投资胜负手放在基础设施供给侧。",
                            "key_points": ["算力", "电力"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )


def test_research_daily_brief_writes_html_publishes_and_sends(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    text_path = tmp_path / "article.txt"
    text_path.write_text(
        "AI data center power demand and chip supply.", encoding="utf-8"
    )
    record = ResearchDocumentRecord(
        source_id="goldman_sachs",
        source_name="高盛",
        url="https://example.com/ai",
        title="AI Winners",
        published_at="June 24, 2026",
        sitemap_lastmod="2026-06-24T10:00:00Z",
        content_type="text/html",
        content_sha256="abc",
        text_path=str(text_path),
        binary_path="",
        status="success",
        error="",
        first_seen_at="2026-06-25T21:30:00+00:00",
        updated_at="2026-06-25T21:30:00+00:00",
        fetched_at="2026-06-25T21:30:00+00:00",
    )
    fetcher = FakeResearchFetcher(record)
    llm = FakeLLMClient()
    sent_targets: list[str] = []

    def fake_send_to_target(
        _sender: object,
        target: str,
        message: object,
    ) -> ChannelSendResult:
        sent_targets.append(target)
        assert "海外投行 AI 研究摘要" in str(message)
        return ChannelSendResult(provider="fake", target=target, ok=True)

    monkeypatch.setattr(
        "stock_news.core.channels.sender.ChannelSender.send_to_target",
        fake_send_to_target,
    )
    publisher = SimpleNamespace(
        publish=lambda path, remote: AlyPublishResult(
            local_path=path,
            remote_path=f"/remote/{remote}",
            url=f"https://cdn.example.com/{remote}",
        )
    )

    result = run_research_daily_brief_task(
        config=AppConfig(),
        now=datetime(2026, 6, 25, 21, 30, tzinfo=timezone.utc),
        output_root=tmp_path / "out",
        max_pages=2,
        max_documents=3,
        provider="mimo",
        thinking_enabled=True,
        channel_targets=["dreamboys", "wecom-push-2"],
        llm_client=llm,
        publisher=publisher,
        fetcher=fetcher,
    )

    assert fetcher.sync_called is True
    assert fetcher.candidate_since == datetime(2026, 6, 23, 21, 30, tzinfo=timezone.utc)
    assert fetcher.fetched_start == datetime(2026, 6, 23, 21, 30, tzinfo=timezone.utc)
    assert fetcher.fetched_end == datetime(
        2026, 6, 25, 21, 30, 0, 1, tzinfo=timezone.utc
    )
    assert llm.provider == "mimo"
    assert llm.overrides["thinking_enabled"] is True
    assert result.html_path.exists()
    html = result.html_path.read_text(encoding="utf-8")
    assert "AI 基建和电力约束" in html
    assert "统计窗口：近 48 小时" in html
    assert result.publish_result is not None
    assert result.publish_result.url.endswith("/2026-06-25/research-ai.html")
    assert sent_targets == ["dreamboys", "wecom-push-2"]


def test_research_daily_brief_skips_old_published_documents(
    tmp_path: Path,
) -> None:
    text_path = tmp_path / "old.txt"
    text_path.write_text("Old AI article.", encoding="utf-8")
    record = ResearchDocumentRecord(
        source_id="goldman_sachs",
        source_name="高盛",
        url="https://example.com/old-ai",
        title="Old AI",
        published_at="June 12, 2026",
        sitemap_lastmod="2026-06-12T10:00:00Z",
        content_type="text/html",
        content_sha256="abc",
        text_path=str(text_path),
        binary_path="",
        status="success",
        error="",
        first_seen_at="2026-06-25T21:30:00+00:00",
        updated_at="2026-06-25T21:30:00+00:00",
        fetched_at="2026-06-25T21:30:00+00:00",
    )

    result = run_research_daily_brief_task(
        config=AppConfig(),
        now=datetime(2026, 6, 25, 21, 30, tzinfo=timezone.utc),
        output_root=tmp_path / "out",
        fetch=False,
        publish=False,
        send=False,
        fetcher=FakeResearchFetcher(record),
    )

    assert result.documents == ()
    assert "近 48 小时没有抓到新的" in result.summary.summary
