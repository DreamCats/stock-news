"""晚间 Top 投研逻辑候选评分。

这里把微信原始消息聚合到标的维度，并保留原消息内容簇作为后续 LLM 证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from stock_news.core.market import MarketSQLiteStore
from stock_news.core.source_messages import (
    CatalystTermHit,
    SourceMessage,
    build_catalyst_library,
    content_hash,
    match_catalysts,
)
from stock_news.core.wechat import WechatMessage
from stock_news.models import AppConfig
from stock_news.usecases.strategy_tasks.catalyst_stock_excel.stock_mentions import (
    StockMention,
    StockMentionDetector,
)
from stock_news.usecases.strategy_tasks.evening_top_logic.models import (
    EveningMessageCluster,
    EveningTopLogicCandidate,
)

_CATEGORY_WEIGHTS = {
    "price_supply": 5.0,
    "order_customer": 5.0,
    "capacity_delivery": 4.2,
    "performance_financial": 4.0,
    "policy_regulation": 3.8,
    "technology_product": 3.5,
    "industry_trend": 3.2,
    "institution": 2.8,
    "market_confirmation": 2.4,
    "event_window": 2.0,
    "reverse_risk": -2.0,
}
_MAX_EVIDENCE_MESSAGES_PER_CLUSTER = 2
_MAX_EVIDENCE_MESSAGE_CHARS = 600


def build_evening_top_logic_candidates(
    *,
    config: AppConfig,
    messages: list[WechatMessage],
    limit: int,
) -> tuple[list[EveningTopLogicCandidate], int, int]:
    """从原始消息构建 Top 候选标的。"""

    library = build_catalyst_library(config.catalysts)
    companies = MarketSQLiteStore(config.tushare.db_path).list_companies(
        list_statuses=("L",)
    )
    detector = StockMentionDetector(companies)
    accumulators: dict[str, _CandidateAccumulator] = {}
    catalyst_count = 0
    stock_message_count = 0

    for message in messages:
        match = match_catalysts(_source_message(message), library)
        if not match.has_hit:
            continue
        catalyst_count += 1
        stocks = detector.find(message.content)
        if not stocks:
            continue
        stock_message_count += 1
        for stock in stocks:
            accumulator = accumulators.get(stock.ts_code)
            if accumulator is None:
                accumulator = _CandidateAccumulator(stock=stock)
                accumulators[stock.ts_code] = accumulator
            accumulator.add(message, list(match.hits))

    candidates = [item.to_candidate() for item in accumulators.values()]
    candidates.sort(key=_candidate_sort_key)
    return candidates[:limit], catalyst_count, stock_message_count


@dataclass
class _CandidateAccumulator:
    stock: StockMention
    message_count: int = 0
    total_hit_score: float = 0.0
    senders: dict[str, datetime | None] = field(default_factory=dict)
    catalyst_terms: dict[str, None] = field(default_factory=dict)
    category_names: dict[str, None] = field(default_factory=dict)
    clusters: dict[str, _MessageClusterAccumulator] = field(default_factory=dict)
    first_message_time: datetime | None = None
    last_message_time: datetime | None = None

    def add(self, message: WechatMessage, hits: list[CatalystTermHit]) -> None:
        """加入一条命中该标的的消息。"""

        self.message_count += 1
        sender = message.sender.strip() or "未知发送人"
        current = self.senders.get(sender)
        if current is None or (
            message.message_time is not None
            and current is not None
            and message.message_time < current
        ):
            self.senders[sender] = message.message_time
        self.first_message_time = _earlier(
            self.first_message_time, message.message_time
        )
        self.last_message_time = _later(self.last_message_time, message.message_time)

        unique_hits = {(hit.category_id, hit.term): hit for hit in hits}
        for hit in unique_hits.values():
            self.catalyst_terms.setdefault(hit.term, None)
            self.category_names.setdefault(hit.category_name, None)
            self.total_hit_score += _CATEGORY_WEIGHTS.get(hit.category_id, 2.0)

        cluster_id = content_hash(message.content)
        cluster = self.clusters.get(cluster_id)
        if cluster is None:
            cluster = _MessageClusterAccumulator(
                cluster_id=cluster_id,
                sample=_short_sample(message.content),
            )
            self.clusters[cluster_id] = cluster
        cluster.add(message, list(unique_hits.values()))

    def to_candidate(self) -> EveningTopLogicCandidate:
        clusters = [cluster.to_cluster() for cluster in self.clusters.values()]
        clusters.sort(key=_cluster_sort_key)
        return EveningTopLogicCandidate(
            stock=self.stock,
            score=_score_candidate(
                hit_score=self.total_hit_score,
                message_count=self.message_count,
                sender_count=len(self.senders),
                cluster_count=len(self.clusters),
            ),
            message_count=self.message_count,
            senders=tuple(
                sorted(
                    self.senders,
                    key=lambda sender: (_time_key(self.senders[sender]), sender),
                )
            ),
            catalyst_terms=tuple(self.catalyst_terms),
            category_names=tuple(self.category_names),
            first_message_time=self.first_message_time,
            last_message_time=self.last_message_time,
            message_clusters=tuple(clusters),
        )


@dataclass
class _MessageClusterAccumulator:
    cluster_id: str
    sample: str
    count: int = 0
    senders: dict[str, None] = field(default_factory=dict)
    catalyst_terms: dict[str, None] = field(default_factory=dict)
    category_names: dict[str, None] = field(default_factory=dict)
    evidence_messages: list[str] = field(default_factory=list)
    evidence_hashes: set[str] = field(default_factory=set)
    first_message_time: datetime | None = None
    last_message_time: datetime | None = None

    def add(self, message: WechatMessage, hits: list[CatalystTermHit]) -> None:
        """把同正文消息合并到内容簇。"""

        self.count += 1
        self.senders.setdefault(message.sender.strip() or "未知发送人", None)
        self.first_message_time = _earlier(
            self.first_message_time, message.message_time
        )
        self.last_message_time = _later(self.last_message_time, message.message_time)
        for hit in hits:
            self.catalyst_terms.setdefault(hit.term, None)
            self.category_names.setdefault(hit.category_name, None)
        self._add_evidence_message(message.content)

    def to_cluster(self) -> EveningMessageCluster:
        return EveningMessageCluster(
            cluster_id=self.cluster_id,
            count=self.count,
            first_message_time=self.first_message_time,
            last_message_time=self.last_message_time,
            senders=tuple(sorted(self.senders)),
            catalyst_terms=tuple(self.catalyst_terms),
            category_names=tuple(self.category_names),
            sample=self.sample,
            evidence_messages=tuple(self.evidence_messages),
        )

    def _add_evidence_message(self, content: str) -> None:
        if len(self.evidence_messages) >= _MAX_EVIDENCE_MESSAGES_PER_CLUSTER:
            return
        text = _evidence_message(content)
        if not text:
            return
        key = content_hash(text)
        if key in self.evidence_hashes:
            return
        self.evidence_hashes.add(key)
        self.evidence_messages.append(text)


def _source_message(message: WechatMessage) -> SourceMessage:
    return SourceMessage(
        message_id=message.message_id,
        content=message.content,
        source=message.source,
        sender=message.sender,
        group_name=message.group_name,
        message_time=message.message_time,
    )


def _score_candidate(
    *,
    hit_score: float,
    message_count: int,
    sender_count: int,
    cluster_count: int,
) -> float:
    score = (
        hit_score
        + min(message_count, 20) * 0.6
        + min(sender_count, 10) * 1.5
        + min(cluster_count, 10) * 2.2
    )
    return round(max(score, 0.0), 2)


def _candidate_sort_key(candidate: EveningTopLogicCandidate) -> tuple[object, ...]:
    return (
        -candidate.score,
        -candidate.cluster_count,
        -candidate.message_count,
        _reverse_time_key(candidate.last_message_time),
        candidate.stock.ts_code,
    )


def _cluster_sort_key(cluster: EveningMessageCluster) -> tuple[object, ...]:
    return (
        -cluster.count,
        _time_key(cluster.first_message_time),
        cluster.cluster_id,
    )


def _earlier(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _later(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _time_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "9999-12-31T23:59:59"


def _reverse_time_key(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _short_sample(content: str, *, max_chars: int = 160) -> str:
    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def _evidence_message(content: str) -> str:
    text = " ".join(content.split())
    if len(text) <= _MAX_EVIDENCE_MESSAGE_CHARS:
        return text
    return f"{text[: _MAX_EVIDENCE_MESSAGE_CHARS - 1]}…"
