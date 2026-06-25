"""市场基础信息同步服务。

当前只同步股票公司和代码映射，不拉取或存储历史行情。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stock_news.core.market import MarketSQLiteStore, StockCompany, StockSyncSummary
from stock_news.core.tushare import TushareProxyClient
from stock_news.models import TushareConfig


@dataclass(frozen=True)
class MarketInfo:
    """market.db 基础状态。"""

    db_path: str
    stock_companies: int


def sync_stock_companies(config: TushareConfig) -> StockSyncSummary:
    """从 Tushare 代理同步股票公司基础信息。"""

    client = TushareProxyClient(
        api_url=config.tushare_api_url,
        token=config.token,
        timeout=config.timeout,
    )
    companies = client.stock_basic()
    store = MarketSQLiteStore(config.db_path)
    return store.upsert_companies(companies)


def search_stock_companies(
    config: TushareConfig,
    keyword: str,
    *,
    limit: int = 20,
) -> list[StockCompany]:
    """搜索本地 market.db 中的股票公司。"""

    return MarketSQLiteStore(config.db_path).search(keyword, limit=limit)


def market_info(config: TushareConfig) -> MarketInfo:
    """读取 market.db 基础状态。"""

    store = MarketSQLiteStore(config.db_path)
    return MarketInfo(
        db_path=str(Path(config.db_path).expanduser()),
        stock_companies=store.count_companies(),
    )
