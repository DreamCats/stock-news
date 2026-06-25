"""项目进程内调度 core 能力。

这里提供定时判断和状态读写，不负责具体业务任务。
"""

from stock_news.core.scheduler.engine import is_daily_due, is_interval_due
from stock_news.core.scheduler.process import (
    SchedulerServerStatus,
    scheduler_server_status,
    start_scheduler_server,
    stop_scheduler_server,
)
from stock_news.core.scheduler.state import (
    ScheduledTaskState,
    ScheduleStateStore,
    TaskRunRecord,
)
from stock_news.core.scheduler.time import parse_clock, parse_duration

__all__ = [
    "ScheduledTaskState",
    "SchedulerServerStatus",
    "ScheduleStateStore",
    "TaskRunRecord",
    "is_daily_due",
    "is_interval_due",
    "parse_clock",
    "parse_duration",
    "scheduler_server_status",
    "start_scheduler_server",
    "stop_scheduler_server",
]
