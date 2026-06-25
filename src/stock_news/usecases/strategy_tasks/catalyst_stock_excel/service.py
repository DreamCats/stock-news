"""策略任务编排。

第一版任务：拉取窗口内微信原始消息，按催化词和标的过滤，生成 Excel 并发送渠道。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from stock_news.core.channels import (
    ChannelFile,
    ChannelMessage,
    ChannelSender,
    ChannelSendResult,
)
from stock_news.core.config import CONFIG_DIR
from stock_news.core.market import MarketSQLiteStore
from stock_news.core.source_messages import (
    SourceMessage,
    build_catalyst_library,
    match_catalysts,
)
from stock_news.core.wechat import TimeWindow, WechatMessage, WechatSQLiteStore
from stock_news.models import AppConfig
from stock_news.usecases.strategy_tasks.catalyst_stock_excel.excel import (
    ExcelTable,
    write_xlsx,
)
from stock_news.usecases.strategy_tasks.catalyst_stock_excel.stock_mentions import (
    StockMention,
    StockMentionDetector,
)
from stock_news.usecases.wechat_fetch import WechatFetchSummary, fetch_wechat_messages


@dataclass(frozen=True)
class CatalystStockRow:
    """Excel 中的一行去重标的。"""

    stock: StockMention
    senders: tuple[str, ...]
    catalyst_terms: tuple[str, ...]
    first_message_time: datetime | None = None


@dataclass(frozen=True)
class CatalystExcelTaskResult:
    """催化词 Excel 策略任务结果。"""

    window: TimeWindow
    excel_path: Path
    fetch_summary: WechatFetchSummary | None
    scanned_messages: int
    catalyst_messages: int
    stock_messages: int
    rows: tuple[CatalystStockRow, ...]
    send_results: tuple[ChannelSendResult, ...] = field(default_factory=tuple)


def run_catalyst_excel_task(
    *,
    config: AppConfig,
    window: TimeWindow,
    sources: list[str] | None = None,
    channel_targets: list[str] | None = None,
    channel_routes: list[str] | None = None,
    now: datetime | None = None,
    refresh: bool = False,
    fetch: bool = True,
    send: bool = True,
    output_root: Path | None = None,
) -> CatalystExcelTaskResult:
    """执行催化词 Excel 策略任务，参数形态面向后续定时任务复用。"""

    current = now or datetime.now().astimezone()
    selected_sources = sources or config.wechat.sources
    fetch_summary: WechatFetchSummary | None = None
    if fetch:
        fetch_summary = fetch_wechat_messages(
            config=config.wechat,
            sources=selected_sources,
            windows=[window],
            now=current,
            refresh=refresh,
        )

    messages = _load_window_messages(config, selected_sources, window)
    rows, catalyst_count, stock_message_count = build_catalyst_stock_rows(
        config=config,
        messages=messages,
    )
    excel_path = _excel_path(output_root or CONFIG_DIR / "data", window)
    write_catalyst_stock_excel(excel_path, rows)

    send_results: list[ChannelSendResult] = []
    if send:
        send_results = _send_excel(
            config=config,
            excel_path=excel_path,
            channel_targets=channel_targets or [],
            channel_routes=channel_routes or [],
        )

    return CatalystExcelTaskResult(
        window=window,
        excel_path=excel_path,
        fetch_summary=fetch_summary,
        scanned_messages=len(messages),
        catalyst_messages=catalyst_count,
        stock_messages=stock_message_count,
        rows=tuple(rows),
        send_results=tuple(send_results),
    )


def build_catalyst_stock_rows(
    *,
    config: AppConfig,
    messages: list[WechatMessage],
) -> tuple[list[CatalystStockRow], int, int]:
    """从原始消息生成按标的去重、推荐人合并的 Excel 行。"""

    library = build_catalyst_library(config.catalysts)
    companies = MarketSQLiteStore(config.tushare.db_path).list_companies(
        list_statuses=("L",)
    )
    detector = StockMentionDetector(companies)
    rows: dict[str, _RowAccumulator] = {}
    catalyst_count = 0
    stock_message_count = 0

    for message in messages:
        result = match_catalysts(_source_message(message), library)
        if not result.has_hit:
            continue
        catalyst_count += 1
        stocks = detector.find(message.content)
        if not stocks:
            continue
        stock_message_count += 1
        sender = message.sender.strip() or "未知发送人"
        catalyst_terms = [hit.term for hit in result.hits]
        for stock in stocks:
            accumulator = rows.get(stock.ts_code)
            if accumulator is None:
                accumulator = _RowAccumulator(stock=stock)
                rows[stock.ts_code] = accumulator
            accumulator.add(sender, message.message_time, catalyst_terms)

    ordered = sorted(
        (item.to_row() for item in rows.values()),
        key=lambda row: (_time_key(row.first_message_time), row.stock.ts_code),
    )
    return ordered, catalyst_count, stock_message_count


def write_catalyst_stock_excel(path: Path, rows: list[CatalystStockRow]) -> Path:
    """写入催化词标的 Excel。"""

    table = ExcelTable(
        headers=["序号", "标的", "出现时间", "推荐人", "催化词"],
        rows=[
            [
                index,
                row.stock.label,
                _format_message_time(row.first_message_time),
                "、".join(row.senders),
                "、".join(row.catalyst_terms),
            ]
            for index, row in enumerate(rows, start=1)
        ],
        sheet_name="催化标的",
    )
    return write_xlsx(path, table)


@dataclass
class _RowAccumulator:
    stock: StockMention
    senders: dict[str, datetime | None] = field(default_factory=dict)
    catalyst_terms: dict[str, None] = field(default_factory=dict)
    first_message_time: datetime | None = None

    def add(
        self,
        sender: str,
        message_time: datetime | None,
        catalyst_terms: list[str],
    ) -> None:
        current = self.senders.get(sender)
        if current is None or (
            message_time is not None and current is not None and message_time < current
        ):
            self.senders[sender] = message_time
        for term in catalyst_terms:
            self.catalyst_terms.setdefault(term, None)
        if self.first_message_time is None:
            self.first_message_time = message_time
        elif message_time is not None and message_time < self.first_message_time:
            self.first_message_time = message_time

    def to_row(self) -> CatalystStockRow:
        senders = sorted(
            self.senders,
            key=lambda sender: (_time_key(self.senders[sender]), sender),
        )
        return CatalystStockRow(
            stock=self.stock,
            senders=tuple(senders),
            catalyst_terms=tuple(self.catalyst_terms),
            first_message_time=self.first_message_time,
        )


def _load_window_messages(
    config: AppConfig,
    sources: list[str],
    window: TimeWindow,
) -> list[WechatMessage]:
    store = WechatSQLiteStore(config.wechat.db_path)
    messages: list[WechatMessage] = []
    for source in sources:
        messages.extend(store.list_messages(source=source, window=window))
    messages.sort(key=lambda item: (item.message_time, item.message_id))
    return messages


def _source_message(message: WechatMessage) -> SourceMessage:
    return SourceMessage(
        message_id=message.message_id,
        content=message.content,
        source=message.source,
        sender=message.sender,
        group_name=message.group_name,
        message_time=message.message_time,
    )


def _excel_path(output_root: Path, window: TimeWindow) -> Path:
    date = window.end.date().isoformat()
    start = window.start.strftime("%H%M")
    end = window.end.strftime("%H%M")
    return output_root / date / "excel" / f"catalyst-stocks-{start}-{end}.xlsx"


def _time_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "9999-12-31T23:59:59"


def _format_message_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else ""


def _send_excel(
    *,
    config: AppConfig,
    excel_path: Path,
    channel_targets: list[str],
    channel_routes: list[str],
) -> list[ChannelSendResult]:
    sender = ChannelSender(config.channel)
    message = ChannelMessage(
        file=ChannelFile(path=excel_path, file_name=excel_path.name)
    )
    results = sender.send_to_targets(channel_targets, message)
    for route in channel_routes:
        results.extend(sender.send_route(route, message))
    return results
