"""策略任务 usecase。

这里放可被 CLI 或定时任务复用的策略任务编排。
"""

from stock_news.usecases.strategy_tasks.catalyst_stock_excel import (
    CatalystExcelTaskResult,
    CatalystStockRow,
    build_catalyst_stock_rows,
    run_catalyst_excel_task,
    write_catalyst_stock_excel,
)
from stock_news.usecases.strategy_tasks.evening_top_logic import (
    EveningLogicItem,
    EveningMessageCluster,
    EveningTopLogicCandidate,
    EveningTopLogicTaskResult,
    build_evening_top_logic_candidates,
    run_evening_top_logic_task,
)

__all__ = [
    "CatalystExcelTaskResult",
    "CatalystStockRow",
    "EveningLogicItem",
    "EveningMessageCluster",
    "EveningTopLogicCandidate",
    "EveningTopLogicTaskResult",
    "build_catalyst_stock_rows",
    "build_evening_top_logic_candidates",
    "run_catalyst_excel_task",
    "run_evening_top_logic_task",
    "write_catalyst_stock_excel",
]
