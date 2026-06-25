"""通用并发能力。

这里放不绑定具体业务域的任务池和并发调度工具。
"""

from stock_news.core.concurrency.pool import TaskRun, run_task_pool

__all__ = ["TaskRun", "run_task_pool"]
