"""晚间 Top 投研逻辑任务编排。

这里串起微信拉取、本地候选评分、LLM 精选、HTML 发布和渠道通知。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
from stock_news.core.wechat import TimeWindow, WechatMessage, WechatSQLiteStore
from stock_news.models import AppConfig
from stock_news.usecases.strategy_tasks.evening_top_logic.html import (
    render_evening_top_logic_html,
)
from stock_news.usecases.strategy_tasks.evening_top_logic.llm import (
    select_evening_top_logic,
)
from stock_news.usecases.strategy_tasks.evening_top_logic.models import (
    EveningTopLogicTaskResult,
)
from stock_news.usecases.strategy_tasks.evening_top_logic.scoring import (
    build_evening_top_logic_candidates,
)
from stock_news.usecases.wechat_fetch import WechatFetchSummary, fetch_wechat_messages


def run_evening_top_logic_task(
    *,
    config: AppConfig,
    window: TimeWindow,
    sources: list[str] | None = None,
    now: datetime | None = None,
    refresh: bool = False,
    fetch: bool = True,
    publish: bool = True,
    send: bool = True,
    output_root: Path | None = None,
    provider: str = "mimo",
    thinking_enabled: bool = True,
    thinking_budget_tokens: int | None = None,
    top_candidates: int = 50,
    top_final: int = 32,
    channel_targets: list[str] | None = None,
    channel_routes: list[str] | None = None,
    llm_client: LLMClient | None = None,
    publisher: AlyPublisher | None = None,
) -> EveningTopLogicTaskResult:
    """执行晚间 Top 投研逻辑任务。"""

    current = now or datetime.now().astimezone()
    selected_sources = sources or config.wechat.sources
    fetch_summary: WechatFetchSummary | None = None
    if fetch:
        fetch_summary = fetch_wechat_messages(
            config=config.wechat,
            sources=selected_sources,
            windows=[window],
            now=current,
            refresh=refresh,
        )

    messages = _load_window_messages(config, selected_sources, window)
    candidates, catalyst_count, stock_message_count = (
        build_evening_top_logic_candidates(
            config=config,
            messages=messages,
            limit=top_candidates,
        )
    )
    selection = select_evening_top_logic(
        llm_config=config.models,
        candidates=candidates,
        final_count=top_final,
        provider=provider,
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=thinking_budget_tokens,
        client=llm_client,
    )

    html_path = _html_path(output_root or CONFIG_DIR / "data", window)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        render_evening_top_logic_html(
            selection=selection,
            window=window,
            generated_at=current,
        ),
        encoding="utf-8",
    )

    publish_result: AlyPublishResult | None = None
    if publish:
        publish_result = (publisher or AlyPublisher(config.aly)).publish(
            html_path,
            _remote_relative_path(window),
        )

    send_results: list[ChannelSendResult] = []
    if send:
        if publish_result is None:
            raise ValueError("发送晚间 Top 逻辑前必须先发布 Aly 链接")
        send_results = _send_summary(
            config=config,
            selection_summary=selection.summary,
            url=publish_result.url,
            item_count=len(selection.items),
            channel_targets=channel_targets or [],
            channel_routes=channel_routes or [],
        )

    return EveningTopLogicTaskResult(
        window=window,
        html_path=html_path,
        fetch_summary=fetch_summary,
        scanned_messages=len(messages),
        catalyst_messages=catalyst_count,
        stock_messages=stock_message_count,
        candidates=tuple(candidates),
        selection=selection,
        publish_result=publish_result,
        send_results=tuple(send_results),
    )


def _load_window_messages(
    config: AppConfig,
    sources: list[str],
    window: TimeWindow,
) -> list[WechatMessage]:
    store = WechatSQLiteStore(config.wechat.db_path)
    messages: list[WechatMessage] = []
    for source in sources:
        messages.extend(store.list_messages(source=source, window=window))
    messages.sort(key=lambda item: (item.message_time, item.message_id))
    return messages


def _html_path(output_root: Path, window: TimeWindow) -> Path:
    date = window.end.date().isoformat()
    return output_root / date / "evening_top_logic" / "top32.html"


def _remote_relative_path(window: TimeWindow) -> str:
    date = window.end.date().isoformat()
    return f"{date}/top32.html"


def _send_summary(
    *,
    config: AppConfig,
    selection_summary: str,
    url: str,
    item_count: int,
    channel_targets: list[str],
    channel_routes: list[str],
) -> list[ChannelSendResult]:
    message = _summary_message(
        selection_summary=selection_summary,
        url=url,
        item_count=item_count,
    )
    sender = ChannelSender(config.channel)
    results: list[ChannelSendResult] = []
    for target in channel_targets:
        results.append(sender.send_to_target(target, message))
    for route in channel_routes:
        results.extend(sender.send_route(route, message))
    return results


def _summary_message(
    *,
    selection_summary: str,
    url: str,
    item_count: int,
) -> ChannelMessage:
    title = f"今晚值得重点看的 {item_count} 条投研逻辑"
    link_text = f"点击查看今晚 Top{item_count} 投研逻辑"
    markdown = f"【{title}】\n{selection_summary}\n\n[{link_text}]({url})"
    return ChannelMessage(
        markdown=markdown,
        rich_text=RichTextContent(
            title=title,
            paragraphs=[
                [RichTextElement(text=selection_summary)],
                [RichTextElement(text=link_text, tag="a", href=url)],
            ],
        ),
    )
