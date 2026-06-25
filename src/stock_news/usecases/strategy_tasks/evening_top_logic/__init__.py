"""晚间 Top 投研逻辑任务。

这里导出每天收盘后聚合催化消息、LLM 精选 Top 标的并发布 HTML 的任务入口。
"""

from stock_news.usecases.strategy_tasks.evening_top_logic.models import (
    EveningLogicItem,
    EveningMessageCluster,
    EveningTopLogicCandidate,
    EveningTopLogicTaskResult,
)
from stock_news.usecases.strategy_tasks.evening_top_logic.scoring import (
    build_evening_top_logic_candidates,
)
from stock_news.usecases.strategy_tasks.evening_top_logic.service import (
    run_evening_top_logic_task,
)

__all__ = [
    "EveningLogicItem",
    "EveningMessageCluster",
    "EveningTopLogicCandidate",
    "EveningTopLogicTaskResult",
    "build_evening_top_logic_candidates",
    "run_evening_top_logic_task",
]
