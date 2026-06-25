"""通用任务池测试。"""

from __future__ import annotations

from threading import Event

from stock_news.core.concurrency import run_task_pool


def test_run_task_pool_refills_worker_when_any_task_finishes() -> None:
    c_started = Event()
    tasks = ["a", "b", "c"]

    def runner(task: str) -> str:
        if task == "b" and not c_started.wait(timeout=1):
            raise AssertionError("c 任务没有在 b 完成前补位执行")
        if task == "c":
            c_started.set()
        return task

    results = run_task_pool(tasks, runner, workers=2)

    assert all(item.ok for item in results)
    assert {item.value for item in results} == {"a", "b", "c"}


def test_run_task_pool_captures_task_error() -> None:
    tasks = ["a"]

    def runner(task: str) -> str:
        raise RuntimeError(task)

    results = run_task_pool(tasks, runner, workers=1)

    assert len(results) == 1
    assert results[0].task == "a"
    assert not results[0].ok
    assert isinstance(results[0].error, RuntimeError)
