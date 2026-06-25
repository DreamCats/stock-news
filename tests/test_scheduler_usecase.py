"""项目内定时任务用例测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_news.core.scheduler import ScheduleStateStore
from stock_news.models import AppConfig
from stock_news.usecases.scheduler.service import (
    TASK_CATALYST_STOCK_EXCEL,
    TASK_TUSHARE_SYNC,
    TASK_WECHAT_FETCH,
    SchedulerActions,
    build_schedule_status,
    due_task_ids,
    run_due_tasks,
    run_scheduled_task,
)


def test_due_task_ids_respects_interval_and_daily_time(tmp_path: Path) -> None:
    cfg = AppConfig()
    store = ScheduleStateStore(tmp_path / "schedule_state.json")
    now = datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc)

    assert due_task_ids(cfg, store, now=now) == [
        TASK_WECHAT_FETCH,
        TASK_TUSHARE_SYNC,
        TASK_CATALYST_STOCK_EXCEL,
    ]

    store.mark_finished(
        TASK_WECHAT_FETCH,
        started_at=now,
        finished_at=now,
        status="success",
        message="ok",
    )
    store.mark_finished(
        TASK_TUSHARE_SYNC,
        started_at=now,
        finished_at=now,
        status="success",
        message="ok",
    )
    store.mark_finished(
        TASK_CATALYST_STOCK_EXCEL,
        started_at=now,
        finished_at=now,
        status="success",
        message="ok",
    )

    assert due_task_ids(cfg, store, now=now + timedelta(minutes=10)) == []
    assert due_task_ids(cfg, store, now=now + timedelta(minutes=31)) == [
        TASK_WECHAT_FETCH
    ]
    assert due_task_ids(cfg, store, now=now + timedelta(minutes=61)) == [
        TASK_WECHAT_FETCH,
        TASK_CATALYST_STOCK_EXCEL,
    ]


def test_catalyst_excel_due_respects_active_window(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.schedule.wechat_fetch.enabled = False
    cfg.schedule.tushare_sync.enabled = False
    store = ScheduleStateStore(tmp_path / "schedule_state.json")

    assert (
        due_task_ids(
            cfg,
            store,
            now=datetime(2026, 6, 25, 8, 59, tzinfo=timezone.utc),
        )
        == []
    )
    assert due_task_ids(
        cfg,
        store,
        now=datetime(2026, 6, 25, 9, 0, 30, tzinfo=timezone.utc),
    ) == [TASK_CATALYST_STOCK_EXCEL]
    assert (
        due_task_ids(
            cfg,
            store,
            now=datetime(2026, 6, 25, 23, 1, tzinfo=timezone.utc),
        )
        == []
    )


def test_run_due_tasks_records_success_without_real_network(tmp_path: Path) -> None:
    cfg = AppConfig()
    store = ScheduleStateStore(tmp_path / "schedule_state.json")
    now = datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc)
    actions = SchedulerActions(
        wechat_fetch=lambda _cfg, _now: "wechat ok",
        tushare_sync=lambda _cfg, _now: "market ok",
        catalyst_stock_excel=lambda _cfg, _now: "excel ok",
    )

    runs = run_due_tasks(cfg, store, now=now, actions=actions)
    status = build_schedule_status(cfg, store, now=now)

    assert [item.task_id for item in runs] == [
        TASK_WECHAT_FETCH,
        TASK_TUSHARE_SYNC,
        TASK_CATALYST_STOCK_EXCEL,
    ]
    assert all(item.ok for item in runs)
    assert [item.last_status for item in status] == [
        "success",
        "success",
        "success",
    ]
    assert [item.last_message for item in status] == [
        "wechat ok",
        "market ok",
        "excel ok",
    ]


def test_run_scheduled_task_records_failure(tmp_path: Path) -> None:
    cfg = AppConfig()
    store = ScheduleStateStore(tmp_path / "schedule_state.json")
    now = datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc)
    actions = SchedulerActions(
        wechat_fetch=lambda _cfg, _now: (_ for _ in ()).throw(RuntimeError("boom")),
        tushare_sync=lambda _cfg, _now: "market ok",
        catalyst_stock_excel=lambda _cfg, _now: "excel ok",
    )

    run = run_scheduled_task(
        cfg,
        store,
        TASK_WECHAT_FETCH,
        now=now,
        actions=actions,
    )
    state = store.get(TASK_WECHAT_FETCH)

    assert run.ok is False
    assert run.message == "boom"
    assert state.last_status == "failed"
    assert state.last_message == "boom"
