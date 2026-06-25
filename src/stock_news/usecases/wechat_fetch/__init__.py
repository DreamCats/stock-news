"""微信数据源拉取用例。

这里编排配置、HTTP client、切片并发和 SQLite 增量写入。
"""

from stock_news.usecases.wechat_fetch.service import (
    WechatFetchSummary,
    fetch_wechat_messages,
)

__all__ = ["WechatFetchSummary", "fetch_wechat_messages"]
