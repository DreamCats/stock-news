"""策略任务 usecase 测试。"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from stock_news.core.aly import AlyPublishResult
from stock_news.core.channels import ChannelSendResult
from stock_news.core.market import MarketSQLiteStore, StockCompany
from stock_news.core.wechat import TimeWindow, WechatMessage, WechatSQLiteStore
from stock_news.models import AppConfig
from stock_news.usecases.strategy_tasks import (
    build_catalyst_stock_rows,
    build_evening_top_logic_candidates,
    run_catalyst_excel_task,
    run_evening_top_logic_task,
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


def test_evening_top_logic_candidates_include_message_clusters(
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
        _message("贵州茅台涨价，强推", sender="张三", minute=1),
        _message("贵州茅台涨价，强推", sender="李四", minute=2),
        _message("贵州茅台新签订单，供货", sender="王五", minute=3),
        _message("平安银行涨价", sender="赵六", minute=4),
    ]

    candidates, catalyst_count, stock_message_count = (
        build_evening_top_logic_candidates(
            config=cfg,
            messages=messages,
            limit=50,
        )
    )

    assert catalyst_count == 4
    assert stock_message_count == 4
    assert candidates[0].stock.label == "贵州茅台(600519.SH)"
    assert candidates[0].message_count == 3
    assert candidates[0].cluster_count == 2
    assert candidates[0].senders == ("张三", "李四", "王五")
    assert candidates[0].message_clusters[0].count == 2
    assert candidates[0].message_clusters[0].sample == "贵州茅台涨价，强推"
    assert candidates[0].message_clusters[0].evidence_messages == (
        "贵州茅台涨价，强推",
    )
    assert "涨价" in candidates[0].catalyst_terms
    assert "订单 / 客户" in candidates[0].category_names


def test_run_evening_top_logic_task_writes_html_and_publishes(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path)
    MarketSQLiteStore(cfg.tushare.db_path).upsert_companies(
        [StockCompany(ts_code="600519.SH", symbol="600519", name="贵州茅台")]
    )
    window = TimeWindow(
        start=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 25, 21, 0, tzinfo=timezone.utc),
    )
    WechatSQLiteStore(cfg.wechat.db_path).save_messages(
        [
            _message("贵州茅台涨价，强推，渠道库存低位", sender="张三", minute=1),
            _message("贵州茅台涨价，强推，渠道库存低位", sender="李四", minute=2),
        ]
    )
    captured_prompt: dict[str, object] = {}

    def fake_chat_text(prompt: str, **kwargs: object) -> SimpleNamespace:
        captured_prompt["prompt"] = prompt
        captured_prompt["kwargs"] = kwargs
        return SimpleNamespace(
            content=(
                '{"summary":"今晚主线集中在高确定性涨价线索。",'
                '"items":[{"ts_code":"600519.SH","title":"白酒涨价确认",'
                '"reason":"涨价消息被不同发送人重复传播，叠加强推语义，'
                '后续需要验证渠道库存和终端接受度。",'
                '"evidence_description":"多条线索指向同一涨价方向，'
                '并且库存低位强化了价格弹性，需要继续跟踪终端反馈。",'
                '"key_catalysts":["涨价","强推"]}]}'
            )
        )

    fake_client = SimpleNamespace(
        chat_text=fake_chat_text,
    )
    fake_publisher = SimpleNamespace(
        publish=lambda path, remote: AlyPublishResult(
            local_path=path,
            remote_path=f"/usr/share/caddy/stock-news/{remote}",
            url=f"https://example.com/stock-news/{remote}",
        )
    )

    result = run_evening_top_logic_task(
        config=cfg,
        window=window,
        fetch=False,
        publish=True,
        send=False,
        output_root=tmp_path / "data",
        top_candidates=50,
        top_final=1,
        llm_client=fake_client,
        publisher=fake_publisher,
    )

    assert result.html_path.exists()
    assert result.publish_result is not None
    assert result.publish_result.url.endswith("/2026-06-25/top32.html")
    assert len(result.selection.items) == 1
    assert result.candidates[0].cluster_count == 1
    prompt = json.loads(str(captured_prompt["prompt"]))
    cluster_payload = prompt["candidates"][0]["message_clusters"][0]
    assert cluster_payload["evidence_messages"] == ["贵州茅台涨价，强推，渠道库存低位"]
    assert captured_prompt["kwargs"]["provider_overrides"] == {"thinking_enabled": True}
    html = result.html_path.read_text(encoding="utf-8")
    assert "今晚值得重点看的 1 条投研逻辑" in html
    assert "白酒涨价确认" in html
    assert "证据组织" in html
    assert "多条线索指向同一涨价方向" in html
    assert "查看原消息内容簇摘要" not in html
    assert "贵州茅台涨价，强推，渠道库存低位" not in html


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
