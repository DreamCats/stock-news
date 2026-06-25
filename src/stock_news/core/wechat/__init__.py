"""微信数据源 core 能力。

这里放微信原始消息模型和 SQLite 增量存储，不包含 CLI 参数解析。
"""

from stock_news.core.wechat.client import WechatAPIError, WechatHTTPClient
from stock_news.core.wechat.fetch_plan import (
    FetchSlice,
    build_fetch_slices,
    plan_incremental_slices,
    split_time_window,
)
from stock_news.core.wechat.models import TimeWindow, WechatMessage
from stock_news.core.wechat.sqlite_store import (
    WechatSQLiteStore,
    WindowFetchState,
    WriteSummary,
)

__all__ = [
    "FetchSlice",
    "TimeWindow",
    "WechatMessage",
    "WechatAPIError",
    "WechatHTTPClient",
    "WechatSQLiteStore",
    "WindowFetchState",
    "WriteSummary",
    "build_fetch_slices",
    "plan_incremental_slices",
    "split_time_window",
]
