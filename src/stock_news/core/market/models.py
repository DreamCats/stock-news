"""市场基础信息模型。

当前只描述股票公司和代码映射，不包含任何历史行情字段。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class StockCompany:
    """股票公司基础信息。"""

    ts_code: str
    symbol: str
    name: str
    area: str = ""
    industry: str = ""
    market: str = ""
    list_date: str = ""
    list_status: str = "L"

    @property
    def row_hash(self) -> str:
        """用于判断基础信息是否变化的稳定 hash。"""

        data = {
            "ts_code": self.ts_code,
            "symbol": self.symbol,
            "name": self.name,
            "area": self.area,
            "industry": self.industry,
            "market": self.market,
            "list_date": self.list_date,
            "list_status": self.list_status,
        }
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StockSyncSummary:
    """股票基础信息同步结果。"""

    fetched: int
    inserted: int
    updated: int
    unchanged: int
