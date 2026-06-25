"""催化标的 Excel 策略任务。

任务流程是微信窗口拉取、催化词过滤、标的识别、推荐人合并、生成 Excel 并发送渠道。
"""

from stock_news.usecases.strategy_tasks.catalyst_stock_excel.service import (
    CatalystExcelTaskResult,
    CatalystStockRow,
    build_catalyst_stock_rows,
    run_catalyst_excel_task,
    write_catalyst_stock_excel,
)

__all__ = [
    "CatalystExcelTaskResult",
    "CatalystStockRow",
    "build_catalyst_stock_rows",
    "run_catalyst_excel_task",
    "write_catalyst_stock_excel",
]
