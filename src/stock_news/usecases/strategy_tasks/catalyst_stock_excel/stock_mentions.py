"""策略任务股票标的识别。

当前只基于 market.db 中的股票公司名称和代码做本地匹配，不访问外部服务。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

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
        self.matchers = [
            _CompanyMatcher(
                company=company,
                ts_code_pattern=_code_pattern(company.ts_code),
                symbol_pattern=_code_pattern(company.symbol),
            )
            for company in companies
            if company.ts_code and company.symbol and company.name
        ]

    def find(self, content: str) -> list[StockMention]:
        """识别正文中的股票标的，按公司列表顺序去重。"""

        mentions: list[StockMention] = []
        seen: set[str] = set()
        for matcher in self.matchers:
            company = matcher.company
            if company.ts_code in seen:
                continue
            if not _matches_company(content, matcher):
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


@dataclass(frozen=True)
class _CompanyMatcher:
    """预编译后的单只股票匹配器。"""

    company: StockCompany
    ts_code_pattern: Pattern[str]
    symbol_pattern: Pattern[str]


def _matches_company(content: str, matcher: _CompanyMatcher) -> bool:
    company = matcher.company
    if matcher.ts_code_pattern.search(content):
        return True
    if matcher.symbol_pattern.search(content):
        return True
    return len(company.name) >= 2 and company.name in content


def _code_pattern(code: str) -> Pattern[str]:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])"
    return re.compile(pattern, flags=re.IGNORECASE)
