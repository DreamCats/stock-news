"""固定 worker 的通用任务池。

任务池会保持固定并发数，任意任务完成后立刻补入队列里的下一个任务。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Generic, TypeVar

TTask = TypeVar("TTask")
TResult = TypeVar("TResult")


@dataclass(frozen=True)
class TaskRun(Generic[TTask, TResult]):
    """一个任务的执行结果。"""

    task: TTask
    ok: bool
    value: TResult | None = None
    error: BaseException | None = None


def run_task_pool(
    tasks: Sequence[TTask],
    runner: Callable[[TTask], TResult],
    *,
    workers: int,
) -> list[TaskRun[TTask, TResult]]:
    """并发执行任务，谁先完成就立刻补下一个。"""

    if workers < 1:
        raise ValueError("workers 必须大于等于 1")
    if not tasks:
        return []

    pending: deque[TTask] = deque(tasks)
    running: dict[Future[TResult], TTask] = {}
    results: list[TaskRun[TTask, TResult]] = []

    def submit_until_full(executor: ThreadPoolExecutor) -> None:
        while pending and len(running) < workers:
            task = pending.popleft()
            running[executor.submit(runner, task)] = task

    with ThreadPoolExecutor(max_workers=workers) as executor:
        submit_until_full(executor)
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                task = running.pop(future)
                try:
                    results.append(
                        TaskRun(
                            task=task,
                            ok=True,
                            value=future.result(),
                        )
                    )
                except BaseException as exc:
                    results.append(
                        TaskRun(
                            task=task,
                            ok=False,
                            error=exc,
                        )
                    )
                submit_until_full(executor)
    return results
