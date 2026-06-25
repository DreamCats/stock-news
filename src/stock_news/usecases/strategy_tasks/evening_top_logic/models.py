"""晚间 Top 投研逻辑数据模型。

这里描述候选标的、原消息内容簇、LLM 精选结果和任务执行结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from stock_news.core.aly import AlyPublishResult
from stock_news.core.channels import ChannelSendResult
from stock_news.core.wechat import TimeWindow
from stock_news.usecases.strategy_tasks.catalyst_stock_excel.stock_mentions import (
    StockMention,
)
from stock_news.usecases.wechat_fetch import WechatFetchSummary


@dataclass(frozen=True)
class EveningMessageCluster:
    """同一标的下的原消息内容簇。"""

    cluster_id: str
    count: int
    first_message_time: datetime | None
    last_message_time: datetime | None
    senders: tuple[str, ...]
    catalyst_terms: tuple[str, ...]
    category_names: tuple[str, ...]
    sample: str
    evidence_messages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EveningTopLogicCandidate:
    """进入 LLM 精选前的 Top 候选标的。"""

    stock: StockMention
    score: float
    message_count: int
    senders: tuple[str, ...]
    catalyst_terms: tuple[str, ...]
    category_names: tuple[str, ...]
    first_message_time: datetime | None
    last_message_time: datetime | None
    message_clusters: tuple[EveningMessageCluster, ...] = field(default_factory=tuple)

    @property
    def cluster_count(self) -> int:
        """返回原消息内容簇数量。"""

        return len(self.message_clusters)


@dataclass(frozen=True)
class EveningLogicItem:
    """LLM 精选后的最终投研逻辑。"""

    rank: int
    candidate: EveningTopLogicCandidate
    title: str
    reason: str
    evidence_description: str
    key_catalysts: tuple[str, ...]


@dataclass(frozen=True)
class EveningLLMSelection:
    """LLM 返回的摘要和 Top 标的列表。"""

    summary: str
    items: tuple[EveningLogicItem, ...]


@dataclass(frozen=True)
class EveningTopLogicTaskResult:
    """晚间 Top 投研逻辑任务执行结果。"""

    window: TimeWindow
    html_path: Path
    fetch_summary: WechatFetchSummary | None
    scanned_messages: int
    catalyst_messages: int
    stock_messages: int
    candidates: tuple[EveningTopLogicCandidate, ...]
    selection: EveningLLMSelection
    publish_result: AlyPublishResult | None = None
    send_results: tuple[ChannelSendResult, ...] = field(default_factory=tuple)
