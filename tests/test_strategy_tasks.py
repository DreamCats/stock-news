"""策略任务 usecase 测试。"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_news.core.channels import ChannelSendResult
from stock_news.core.market import MarketSQLiteStore, StockCompany
from stock_news.core.wechat import TimeWindow, WechatMessage, WechatSQLiteStore
from stock_news.models import AppConfig
from stock_news.usecases.strategy_tasks import (
    build_catalyst_stock_rows,
    run_catalyst_excel_task,
)
from stock_news.usecases.wechat_fetch import WechatFetchSummary


def test_build_catalyst_stock_rows_dedupes_stock_and_merges_senders(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path)
    MarketSQLiteStore(cfg.tushare.db_path).upsert_companies(
        [
            StockCompany(ts_code="600519.SH", symbol="600519", name="贵州茅台"),
            StockCompany(ts_code="000001.SZ", symbol="000001", name="平安银行"),
        ]
    )
    messages = [
        _message("贵州茅台涨价，继续推荐", sender="张三", minute=1),
        _message("600519 涨价再强调", sender="李四", minute=2),
        _message("平安银行普通聊天", sender="王五", minute=3),
        _message("液冷涨价但没有标的", sender="赵六", minute=4),
    ]

    rows, catalyst_count, stock_message_count = build_catalyst_stock_rows(
        config=cfg,
        messages=messages,
    )

    assert catalyst_count == 3
    assert stock_message_count == 2
    assert len(rows) == 1
    assert rows[0].stock.label == "贵州茅台(600519.SH)"
    assert rows[0].senders == ("张三", "李四")
    assert rows[0].catalyst_terms == ("继续推荐", "涨价")
    assert rows[0].first_message_time == datetime(
        2026, 6, 25, 9, 1, tzinfo=timezone.utc
    )


def test_run_catalyst_excel_task_fetches_writes_and_sends(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    cfg = _config(tmp_path)
    MarketSQLiteStore(cfg.tushare.db_path).upsert_companies(
        [StockCompany(ts_code="600519.SH", symbol="600519", name="贵州茅台")]
    )
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 9, 30, tzinfo=timezone.utc),
    )
    sent_files: list[Path] = []

    def fake_fetch_wechat_messages(**kwargs: object) -> WechatFetchSummary:
        wechat_config = cfg.wechat
        WechatSQLiteStore(wechat_config.db_path).save_messages(
            [_message("贵州茅台涨价，强推", sender="张三", minute=5)]
        )
        return WechatFetchSummary(
            planned=1,
            skipped=0,
            fetched=1,
            inserted=1,
            duplicated=0,
            errors=[],
        )

    def fake_send_to_target(
        self: object,
        target_name: str,
        message: object,
    ) -> ChannelSendResult:
        file = getattr(message, "file")
        sent_files.append(file.path)
        return ChannelSendResult(
            provider="fake",
            target=target_name,
            ok=True,
            message="sent file",
        )

    monkeypatch.setattr(
        "stock_news.usecases.strategy_tasks.catalyst_stock_excel.service."
        "fetch_wechat_messages",
        fake_fetch_wechat_messages,
    )
    monkeypatch.setattr(
        "stock_news.core.channels.sender.ChannelSender.send_to_target",
        fake_send_to_target,
    )

    result = run_catalyst_excel_task(
        config=cfg,
        window=window,
        sources=["个人消息"],
        channel_targets=["dreamboys"],
        output_root=tmp_path / "data",
    )

    assert result.fetch_summary is not None
    assert result.scanned_messages == 1
    assert len(result.rows) == 1
    assert result.rows[0].senders == ("张三",)
    assert result.rows[0].catalyst_terms == ("强推", "涨价")
    assert result.excel_path.exists()
    assert sent_files == [result.excel_path]
    assert result.send_results[0].ok is True
    with zipfile.ZipFile(result.excel_path) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "贵州茅台(600519.SH)" in sheet
    assert "出现时间" in sheet
    assert "2026-06-25 09:05" in sheet
    assert "张三" in sheet
    assert "催化词" in sheet
    assert "涨价" in sheet
    assert "强推" in sheet


def _config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.wechat.db_path = str(tmp_path / "wechat.db")
    cfg.tushare.db_path = str(tmp_path / "market.db")
    return cfg


def _message(content: str, *, sender: str, minute: int) -> WechatMessage:
    return WechatMessage(
        source="个人消息",
        sender=sender,
        message_time=datetime(2026, 6, 25, 9, minute, tzinfo=timezone.utc),
        content=content,
        raw={"content": content},
    )
