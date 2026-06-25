"""调度后台进程管理测试。"""

from __future__ import annotations

import json
from pathlib import Path

from stock_news.core.scheduler import scheduler_server_status


def test_scheduler_server_status_without_pid_file(tmp_path: Path) -> None:
    status = scheduler_server_status(
        pid_file=tmp_path / "schedule.pid",
        log_file=tmp_path / "schedule.log",
    )

    assert status.running is False
    assert status.pid is None
    assert status.message == "未运行"


def test_scheduler_server_status_with_stale_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "schedule.pid"
    pid_file.write_text(
        json.dumps({"pid": 99999999}, ensure_ascii=False),
        encoding="utf-8",
    )

    status = scheduler_server_status(
        pid_file=pid_file,
        log_file=tmp_path / "schedule.log",
    )

    assert status.running is False
    assert status.pid == 99999999
    assert status.message == "pid 文件存在，但进程已退出"
