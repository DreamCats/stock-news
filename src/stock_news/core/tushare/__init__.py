"""Tushare 代理 core 能力。

这里封装 Tushare 代理协议，不直接依赖 tushare 官方包。
"""

from stock_news.core.tushare.client import TushareProxyClient, TushareProxyError

__all__ = ["TushareProxyClient", "TushareProxyError"]
