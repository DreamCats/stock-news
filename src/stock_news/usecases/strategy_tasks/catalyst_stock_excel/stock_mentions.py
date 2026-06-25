"""策略任务股票标的识别。

当前只基于 market.db 中的股票公司名称和代码做本地匹配，不访问外部服务。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stock_news.core.market import StockCompany


@dataclass(frozen=True)
class StockMention:
    """正文中的股票标的命中。"""

    ts_code: str
    symbol: str
    name: str

    @property
    def label(self) -> str:
        """Excel 中展示的标的文本。"""

        return f"{self.name}({self.ts_code})"


class StockMentionDetector:
    """基于本地股票公司列表的标的识别器。"""

    def __init__(self, companies: list[StockCompany]) -> None:
        self.companies = [
            company
            for company in companies
            if company.ts_code and company.symbol and company.name
        ]

    def find(self, content: str) -> list[StockMention]:
        """识别正文中的股票标的，按公司列表顺序去重。"""

        mentions: list[StockMention] = []
        seen: set[str] = set()
        for company in self.companies:
            if company.ts_code in seen:
                continue
            if not _matches_company(content, company):
                continue
            seen.add(company.ts_code)
            mentions.append(
                StockMention(
                    ts_code=company.ts_code,
                    symbol=company.symbol,
                    name=company.name,
                )
            )
        return mentions


def _matches_company(content: str, company: StockCompany) -> bool:
    if _contains_code(content, company.ts_code):
        return True
    if _contains_code(content, company.symbol):
        return True
    return len(company.name) >= 2 and company.name in content


def _contains_code(content: str, code: str) -> bool:
    if not code:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])"
    return re.search(pattern, content, flags=re.IGNORECASE) is not None
