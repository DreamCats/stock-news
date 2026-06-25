"""公开研究源每日摘要任务编排。

这里串起公开研究源增量抓取、近 48 小时记录读取、LLM 中文摘要、HTML 发布和渠道通知。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol

from stock_news.core.aly import AlyPublisher, AlyPublishResult
from stock_news.core.channels import (
    ChannelMessage,
    ChannelSender,
    ChannelSendResult,
    RichTextContent,
    RichTextElement,
)
from stock_news.core.config import CONFIG_DIR
from stock_news.core.llm import LLMClient
from stock_news.core.research_sources import (
    ResearchDocumentRecord,
    ResearchSourceFetcher,
    ResearchSyncSummary,
)
from stock_news.models import AppConfig
from stock_news.usecases.research.html import render_research_daily_brief_html
from stock_news.usecases.research.llm import summarize_research_documents
from stock_news.usecases.research.models import (
    ResearchBriefDocument,
    ResearchDailyBriefTaskResult,
)


class ResearchFetcherLike(Protocol):
    """研究源抓取器协议，方便测试替换真实网络。"""

    def sync(
        self,
        *,
        max_pages: int | None = None,
        refresh: bool = False,
        dry_run: bool = False,
        candidate_since: datetime | None = None,
        now: datetime | None = None,
    ) -> ResearchSyncSummary: ...

    def list_documents(
        self,
        *,
        fetched_start: datetime | None = None,
        fetched_end: datetime | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[ResearchDocumentRecord]: ...


def run_research_daily_brief_task(
    *,
    config: AppConfig,
    now: datetime | None = None,
    fetch: bool = True,
    publish: bool = True,
    send: bool = True,
    refresh: bool = False,
    max_pages: int = 20,
    lookback_hours: int = 48,
    max_documents: int = 30,
    max_chars_per_document: int = 3500,
    provider: str = "mimo",
    thinking_enabled: bool = True,
    thinking_budget_tokens: int | None = None,
    channel_targets: list[str] | None = None,
    channel_routes: list[str] | None = None,
    output_root: Path | None = None,
    llm_client: LLMClient | None = None,
    publisher: AlyPublisher | None = None,
    fetcher: ResearchFetcherLike | None = None,
) -> ResearchDailyBriefTaskResult:
    """执行公开研究源每日摘要任务。"""

    current = now or datetime.now().astimezone()
    research_fetcher = fetcher or ResearchSourceFetcher(config.research_sources)
    window_start, window_end = _lookback_window(current, lookback_hours)
    sync_summary: ResearchSyncSummary | None = None
    if fetch:
        sync_summary = research_fetcher.sync(
            max_pages=max_pages,
            refresh=refresh,
            candidate_since=window_start,
            now=current,
        )

    records = research_fetcher.list_documents(
        fetched_start=window_start,
        fetched_end=window_end + timedelta(microseconds=1),
        status="success",
        limit=max_documents,
    )
    records = _filter_records_by_published(records, window_start)
    documents = _build_documents(records, max_chars_per_document)
    summary = summarize_research_documents(
        llm_config=config.models,
        documents=documents,
        provider=provider,
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=thinking_budget_tokens,
        client=llm_client,
    )

    html_path = _html_path(output_root or CONFIG_DIR / "data", current)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        render_research_daily_brief_html(
            summary=summary,
            documents=documents,
            generated_at=current,
        ),
        encoding="utf-8",
    )

    publish_result: AlyPublishResult | None = None
    if publish:
        publish_result = (publisher or AlyPublisher(config.aly)).publish(
            html_path,
            _remote_relative_path(current),
        )

    send_results: list[ChannelSendResult] = []
    if send:
        if publish_result is None:
            raise ValueError("发送公开研究源摘要前必须先发布 Aly 链接")
        send_results = _send_summary(
            config=config,
            title=summary.title,
            summary=summary.summary,
            url=publish_result.url,
            item_count=len(summary.items),
            channel_targets=channel_targets or [],
            channel_routes=channel_routes or [],
        )

    return ResearchDailyBriefTaskResult(
        generated_at=current,
        html_path=html_path,
        sync_summary=sync_summary,
        documents=tuple(documents),
        summary=summary,
        publish_result=publish_result,
        send_results=tuple(send_results),
    )


def _build_documents(
    records: list[ResearchDocumentRecord],
    max_chars_per_document: int,
) -> list[ResearchBriefDocument]:
    documents: list[ResearchBriefDocument] = []
    for record in records:
        documents.append(
            ResearchBriefDocument(
                source_id=record.source_id,
                source_name=record.source_name,
                title=record.title,
                url=record.url,
                published_at=record.published_at or record.sitemap_lastmod,
                fetched_at=record.fetched_at,
                text_excerpt=_document_excerpt(record, max_chars_per_document),
            )
        )
    return documents


def _document_excerpt(record: ResearchDocumentRecord, max_chars: int) -> str:
    if record.text_path:
        path = Path(record.text_path).expanduser()
        if path.exists():
            return _truncate(
                path.read_text(encoding="utf-8", errors="ignore"), max_chars
            )
    if record.binary_path:
        return "该内容为 PDF 文件，当前只保留标题、来源和原文链接。"
    return ""


def _truncate(value: str, max_chars: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _lookback_window(now: datetime, lookback_hours: int) -> tuple[datetime, datetime]:
    return now - timedelta(hours=lookback_hours), now


def _filter_records_by_published(
    records: list[ResearchDocumentRecord],
    since: datetime,
) -> list[ResearchDocumentRecord]:
    return [
        record
        for record in records
        if (_record_published_datetime(record, since) or datetime.min) >= since
    ]


def _record_published_datetime(
    record: ResearchDocumentRecord,
    reference: datetime,
) -> datetime | None:
    return _parse_research_datetime(
        record.published_at,
        reference,
    ) or _parse_research_datetime(
        record.sitemap_lastmod,
        reference,
    )


def _parse_research_datetime(value: str, reference: datetime) -> datetime | None:
    parsed_iso = _parse_research_iso_datetime(value, reference)
    if parsed_iso is not None:
        return parsed_iso
    parsed_date = _parse_research_date(value)
    if parsed_date is not None:
        return datetime.combine(parsed_date, time.min, tzinfo=reference.tzinfo)
    return None


def _parse_research_iso_datetime(value: str, reference: datetime) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=reference.tzinfo)
    return parsed.astimezone(reference.tzinfo)


def _parse_research_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _html_path(output_root: Path, now: datetime) -> Path:
    return output_root / now.date().isoformat() / "research" / "research-ai.html"


def _remote_relative_path(now: datetime) -> str:
    return f"{now.date().isoformat()}/research-ai.html"


def _send_summary(
    *,
    config: AppConfig,
    title: str,
    summary: str,
    url: str,
    item_count: int,
    channel_targets: list[str],
    channel_routes: list[str],
) -> list[ChannelSendResult]:
    message = _summary_message(
        title=title,
        summary=summary,
        url=url,
        item_count=item_count,
    )
    sender = ChannelSender(config.channel)
    results = sender.send_to_targets(channel_targets, message)
    for route in channel_routes:
        results.extend(sender.send_route(route, message))
    return results


def _summary_message(
    *,
    title: str,
    summary: str,
    url: str,
    item_count: int,
) -> ChannelMessage:
    link_text = "点击查看近 48 小时海外投行 AI 研究摘要"
    markdown = (
        f"【{title}】\n{summary}\n\n"
        f"本次精选 {item_count} 条内容。\n"
        f"[{link_text}]({url})"
    )
    return ChannelMessage(
        markdown=markdown,
        rich_text=RichTextContent(
            title=title,
            paragraphs=[
                [RichTextElement(text=summary)],
                [RichTextElement(text=f"本次精选 {item_count} 条内容。")],
                [RichTextElement(text=link_text, tag="a", href=url)],
            ],
        ),
    )
