"""微信数据源拉取编排。

用例层负责把大窗口拆片、并发调用 API、写入 SQLite，并更新窗口增量状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from stock_news.core.concurrency import run_task_pool
from stock_news.core.wechat import (
    FetchSlice,
    TimeWindow,
    WechatHTTPClient,
    WechatSQLiteStore,
    build_fetch_slices,
    plan_incremental_slices,
)
from stock_news.models import WechatSourceConfig


@dataclass(frozen=True)
class SliceFetchSummary:
    """单个切片的拉取写入结果。"""

    source: str
    start: datetime
    end: datetime
    fetched: int
    inserted: int
    duplicated: int


@dataclass(frozen=True)
class SliceFetchError:
    """单个切片的失败信息。"""

    source: str
    start: datetime
    end: datetime
    error: str


@dataclass(frozen=True)
class WechatFetchSummary:
    """一次微信拉取的汇总结果。"""

    planned: int
    skipped: int
    fetched: int
    inserted: int
    duplicated: int
    errors: list[SliceFetchError]


def fetch_wechat_messages(
    *,
    config: WechatSourceConfig,
    sources: list[str],
    windows: list[TimeWindow],
    now: datetime,
    refresh: bool = False,
) -> WechatFetchSummary:
    """按配置拉取微信消息并增量写入 SQLite。"""

    store = WechatSQLiteStore(Path(config.db_path).expanduser())
    if refresh:
        all_slices = build_fetch_slices(
            sources=sources,
            windows=windows,
            slice_hours=config.fetch.slice_hours,
        )
    else:
        all_slices = plan_incremental_slices(
            sources=sources,
            windows=windows,
            slice_hours=config.fetch.slice_hours,
            store=store,
            now=now,
            safety_margin_minutes=config.fetch.safety_margin_minutes,
        )

    client = WechatHTTPClient(
        base_url=config.base_url,
        timeout=config.timeout,
        auth=config.auth,
    )

    def runner(fetch_slice: FetchSlice) -> SliceFetchSummary:
        for attempt in range(config.fetch.retries + 1):
            try:
                messages = client.fetch(fetch_slice.source, fetch_slice.window)
                write = store.save_messages(messages, now=now)
                store.mark_window_success(
                    fetch_slice.source,
                    fetch_slice.window,
                    message_count=len(messages),
                    fetched_at=now,
                )
                return SliceFetchSummary(
                    source=fetch_slice.source,
                    start=fetch_slice.window.start,
                    end=fetch_slice.window.end,
                    fetched=len(messages),
                    inserted=write.inserted,
                    duplicated=write.duplicated,
                )
            except Exception as exc:
                if attempt >= config.fetch.retries:
                    store.mark_window_failure(
                        fetch_slice.source,
                        fetch_slice.window,
                        error=str(exc),
                        fetched_at=now,
                    )
                    raise
        raise RuntimeError("不可达的微信拉取重试状态")

    runs = run_task_pool(all_slices, runner, workers=config.fetch.workers)
    summaries: list[SliceFetchSummary] = []
    errors: list[SliceFetchError] = []
    for run in runs:
        if run.ok:
            summaries.append(cast(SliceFetchSummary, run.value))
        else:
            errors.append(
                SliceFetchError(
                    source=run.task.source,
                    start=run.task.window.start,
                    end=run.task.window.end,
                    error=str(run.error),
                )
            )

    return WechatFetchSummary(
        planned=len(all_slices),
        skipped=_count_skipped(
            sources=sources,
            windows=windows,
            slice_hours=config.fetch.slice_hours,
            planned=len(all_slices),
        ),
        fetched=sum(item.fetched for item in summaries),
        inserted=sum(item.inserted for item in summaries),
        duplicated=sum(item.duplicated for item in summaries),
        errors=errors,
    )


def _count_skipped(
    *,
    sources: list[str],
    windows: list[TimeWindow],
    slice_hours: int,
    planned: int,
) -> int:
    return (
        len(
            build_fetch_slices(
                sources=sources,
                windows=windows,
                slice_hours=slice_hours,
            )
        )
        - planned
    )
