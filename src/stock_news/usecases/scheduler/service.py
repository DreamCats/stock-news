"""固定定时任务执行服务。

这里只编排当前项目明确需要的固定任务，不恢复通用 jobs workflow。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

from stock_news.core.scheduler import (
    ScheduledTaskState,
    ScheduleStateStore,
    is_daily_due,
    is_interval_due,
    parse_clock,
    parse_duration,
)
from stock_news.core.wechat import TimeWindow
from stock_news.models import AppConfig
from stock_news.usecases.market_sync import sync_stock_companies
from stock_news.usecases.strategy_tasks import run_catalyst_excel_task
from stock_news.usecases.wechat_fetch import fetch_wechat_messages

TaskId = Literal["wechat_fetch", "tushare_sync", "catalyst_stock_excel"]
TASK_WECHAT_FETCH: TaskId = "wechat_fetch"
TASK_TUSHARE_SYNC: TaskId = "tushare_sync"
TASK_CATALYST_STOCK_EXCEL: TaskId = "catalyst_stock_excel"


@dataclass(frozen=True)
class ScheduledRunSummary:
    """一次定时任务执行结果。"""

    task_id: TaskId
    started_at: datetime
    finished_at: datetime
    ok: bool
    message: str


@dataclass(frozen=True)
class ScheduledTaskView:
    """定时任务状态展示模型。"""

    task_id: TaskId
    enabled: bool
    trigger: str
    due: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: str | None
    last_message: str


@dataclass(frozen=True)
class SchedulerActions:
    """定时任务可替换执行动作，方便测试。"""

    wechat_fetch: Callable[[AppConfig, datetime], str]
    tushare_sync: Callable[[AppConfig, datetime], str]
    catalyst_stock_excel: Callable[[AppConfig, datetime], str]


DEFAULT_ACTIONS = SchedulerActions(
    wechat_fetch=lambda cfg, now: _run_wechat_fetch(cfg, now),
    tushare_sync=lambda cfg, now: _run_tushare_sync(cfg, now),
    catalyst_stock_excel=lambda cfg, now: _run_catalyst_stock_excel(cfg, now),
)


def due_task_ids(
    config: AppConfig,
    store: ScheduleStateStore,
    *,
    now: datetime,
) -> list[TaskId]:
    """返回当前应该触发的任务 ID。"""

    if not config.schedule.enabled:
        return []

    due: list[TaskId] = []
    wechat_state = store.get(TASK_WECHAT_FETCH)
    wechat_base_time = wechat_state.last_finished_at or wechat_state.last_started_at
    if config.schedule.wechat_fetch.enabled and is_interval_due(
        now=now,
        every=parse_duration(config.schedule.wechat_fetch.every),
        last_started_at=wechat_base_time,
    ):
        due.append(TASK_WECHAT_FETCH)

    tushare_state = store.get(TASK_TUSHARE_SYNC)
    if config.schedule.tushare_sync.enabled and is_daily_due(
        now=now,
        at=parse_clock(config.schedule.tushare_sync.at),
        last_started_at=tushare_state.last_started_at,
    ):
        due.append(TASK_TUSHARE_SYNC)

    catalyst_state = store.get(TASK_CATALYST_STOCK_EXCEL)
    catalyst_base_time = (
        catalyst_state.last_finished_at or catalyst_state.last_started_at
    )
    catalyst_config = config.schedule.catalyst_stock_excel
    if (
        catalyst_config.enabled
        and _within_active_window(
            now,
            start=parse_clock(catalyst_config.active_start),
            end=parse_clock(catalyst_config.active_end),
        )
        and is_interval_due(
            now=now,
            every=parse_duration(catalyst_config.every),
            last_started_at=catalyst_base_time,
        )
    ):
        due.append(TASK_CATALYST_STOCK_EXCEL)

    return due


def run_due_tasks(
    config: AppConfig,
    store: ScheduleStateStore,
    *,
    now: datetime,
    actions: SchedulerActions = DEFAULT_ACTIONS,
) -> list[ScheduledRunSummary]:
    """执行当前到期任务。"""

    return [
        run_scheduled_task(config, store, task_id, now=now, actions=actions)
        for task_id in due_task_ids(config, store, now=now)
    ]


def run_scheduled_task(
    config: AppConfig,
    store: ScheduleStateStore,
    task_id: TaskId,
    *,
    now: datetime,
    actions: SchedulerActions = DEFAULT_ACTIONS,
) -> ScheduledRunSummary:
    """执行一个固定定时任务，并写入状态。"""

    started_at = now
    store.mark_started(task_id, started_at=started_at)
    try:
        message = _run_action(config, task_id, now, actions)
    except Exception as exc:
        finished_at = datetime.now().astimezone().replace(microsecond=0)
        message = str(exc)
        store.mark_finished(
            task_id,
            started_at=started_at,
            finished_at=finished_at,
            status="failed",
            message=message,
        )
        return ScheduledRunSummary(
            task_id=task_id,
            started_at=started_at,
            finished_at=finished_at,
            ok=False,
            message=message,
        )

    finished_at = datetime.now().astimezone().replace(microsecond=0)
    store.mark_finished(
        task_id,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        message=message,
    )
    return ScheduledRunSummary(
        task_id=task_id,
        started_at=started_at,
        finished_at=finished_at,
        ok=True,
        message=message,
    )


def build_schedule_status(
    config: AppConfig,
    store: ScheduleStateStore,
    *,
    now: datetime,
) -> list[ScheduledTaskView]:
    """构建定时任务状态视图。"""

    states = store.load()
    due = set(due_task_ids(config, store, now=now))
    return [
        _task_view(
            task_id=TASK_WECHAT_FETCH,
            enabled=config.schedule.enabled and config.schedule.wechat_fetch.enabled,
            trigger=(
                f"every={config.schedule.wechat_fetch.every} "
                f"window={config.schedule.wechat_fetch.window}"
            ),
            due=TASK_WECHAT_FETCH in due,
            state=states.get(TASK_WECHAT_FETCH, ScheduledTaskState()),
        ),
        _task_view(
            task_id=TASK_TUSHARE_SYNC,
            enabled=config.schedule.enabled and config.schedule.tushare_sync.enabled,
            trigger=f"at={config.schedule.tushare_sync.at}",
            due=TASK_TUSHARE_SYNC in due,
            state=states.get(TASK_TUSHARE_SYNC, ScheduledTaskState()),
        ),
        _task_view(
            task_id=TASK_CATALYST_STOCK_EXCEL,
            enabled=(
                config.schedule.enabled and config.schedule.catalyst_stock_excel.enabled
            ),
            trigger=(
                f"every={config.schedule.catalyst_stock_excel.every} "
                f"window={config.schedule.catalyst_stock_excel.window} "
                f"active={config.schedule.catalyst_stock_excel.active_start}-"
                f"{config.schedule.catalyst_stock_excel.active_end} "
                "targets="
                f"{','.join(config.schedule.catalyst_stock_excel.channel_targets)}"
            ),
            due=TASK_CATALYST_STOCK_EXCEL in due,
            state=states.get(TASK_CATALYST_STOCK_EXCEL, ScheduledTaskState()),
        ),
    ]


def _run_action(
    config: AppConfig,
    task_id: TaskId,
    now: datetime,
    actions: SchedulerActions,
) -> str:
    if task_id == TASK_WECHAT_FETCH:
        return actions.wechat_fetch(config, now)
    if task_id == TASK_TUSHARE_SYNC:
        return actions.tushare_sync(config, now)
    if task_id == TASK_CATALYST_STOCK_EXCEL:
        return actions.catalyst_stock_excel(config, now)
    raise ValueError(f"未知定时任务: {task_id}")


def _run_wechat_fetch(config: AppConfig, now: datetime) -> str:
    window_size = parse_duration(config.schedule.wechat_fetch.window)
    window = TimeWindow(start=now - window_size, end=now)
    summary = fetch_wechat_messages(
        config=config.wechat,
        sources=config.wechat.sources,
        windows=[window],
        now=now,
    )
    message = (
        f"planned={summary.planned} skipped={summary.skipped} "
        f"fetched={summary.fetched} inserted={summary.inserted} "
        f"duplicated={summary.duplicated}"
    )
    if summary.errors:
        raise RuntimeError(f"{message} errors={len(summary.errors)}")
    return message


def _run_tushare_sync(config: AppConfig, now: datetime) -> str:
    del now
    summary = sync_stock_companies(config.tushare)
    return (
        f"fetched={summary.fetched} inserted={summary.inserted} "
        f"updated={summary.updated} unchanged={summary.unchanged}"
    )


def _run_catalyst_stock_excel(config: AppConfig, now: datetime) -> str:
    schedule = config.schedule.catalyst_stock_excel
    window_size = parse_duration(schedule.window)
    window = TimeWindow(start=now - window_size, end=now)
    result = run_catalyst_excel_task(
        config=config,
        window=window,
        sources=config.wechat.sources,
        channel_targets=schedule.channel_targets,
        channel_routes=schedule.channel_routes,
        now=now,
        fetch=True,
        send=True,
    )
    fetch_summary = result.fetch_summary
    fetch_part = ""
    if fetch_summary is not None:
        fetch_part = (
            f" fetched={fetch_summary.fetched}"
            f" inserted={fetch_summary.inserted}"
            f" errors={len(fetch_summary.errors)}"
        )
        if fetch_summary.errors:
            raise RuntimeError(fetch_part.strip())
    return (
        f"scanned={result.scanned_messages}"
        f" catalyst={result.catalyst_messages}"
        f" stock_messages={result.stock_messages}"
        f" rows={len(result.rows)}"
        f" sent={len(result.send_results)}"
        f" file={result.excel_path}"
        f"{fetch_part}"
    )


def _within_active_window(now: datetime, *, start: time, end: time) -> bool:
    current = now.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _task_view(
    *,
    task_id: TaskId,
    enabled: bool,
    trigger: str,
    due: bool,
    state: ScheduledTaskState,
) -> ScheduledTaskView:
    return ScheduledTaskView(
        task_id=task_id,
        enabled=enabled,
        trigger=trigger,
        due=due,
        last_started_at=state.last_started_at,
        last_finished_at=state.last_finished_at,
        last_status=state.last_status,
        last_message=state.last_message,
    )
