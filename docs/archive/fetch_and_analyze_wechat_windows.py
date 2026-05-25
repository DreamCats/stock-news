#!/usr/bin/env python3
"""Fetch fixed WeChat API windows and generate a first-pass data report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_URL = "https://example.com/api"
SOURCES = ("个人消息", "个人群")
DEFAULT_WINDOWS = (
    ("20260521200000", "20260521203000"),
    ("20260521203000", "20260521210000"),
    ("20260521210000", "20260521213000"),
    ("20260521213000", "20260521220000"),
    ("20260521220000", "20260521223000"),
    ("20260521223000", "20260521230000"),
    ("20260521230000", "20260521233000"),
    ("20260521233000", "20260522000000"),
    ("20260522000000", "20260522003000"),
    ("20260522003000", "20260522010000"),
    ("20260522090000", "20260522093000"),
    ("20260522093000", "20260522100000"),
)

STOCK_KEYWORDS = re.compile(
    r"股份|证券|通信|汽车|消费|医药|银行|电子|机械|计算机|传媒|地产|半导体|"
    r"光模块|公司|业绩|财报|估值|买入|卖出|推荐|看好|目标价|港股|美股|"
    r"A股|板块|个股|策略|宏观|固收|转债|券商|研报|AI|PCB|机器人|"
    r"新能源|光伏|储能|涨停|订单|扩产|投资者|调研|中期策略|股权|收购"
)
RECOMMEND_KEYWORDS = re.compile(
    r"推荐|重点关注|重点推荐|继续看好|坚定看好|买入|加仓|低吸|低开.*吸|"
    r"看多|目标价|弹性|主推|建议关注|持续推荐|强推|关注"
)
EVENT_KEYWORDS = re.compile(r"会议|策略会|邀请|报名|活动|路演|调研|教学|培训|日程|参会")
PRIVATE_NOISE_KEYWORDS = re.compile(r"睡觉|中午去|周末|玩水|皮划艇|浆板|去哪|吃|贵哦|小女生")
TICKER_PATTERN = re.compile(r"\b(?:[036]\d{5}|[A-Z]{1,5})(?:\.(?:SH|SZ|HK|US))?\b")
CHINESE_COMPANY_HINT = re.compile(r"[\u4e00-\u9fff]{2,8}(?:股份|集团|科技|电子|汽车|家居|电器|化学|仪器|生物|药业)")


@dataclass(frozen=True)
class Window:
    start: str
    end: str

    @property
    def label(self) -> str:
        return f"{self.start}_{self.end}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--raw-dir", default="data/wechat_api/raw")
    parser.add_argument("--report-dir", default="data/wechat_api/reports")
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument(
        "--window",
        action="append",
        help="Time window as start,end. Can be passed multiple times.",
    )
    return parser.parse_args()


def parse_windows(values: list[str] | None) -> list[Window]:
    if not values:
        return [Window(start, end) for start, end in DEFAULT_WINDOWS]
    windows: list[Window] = []
    for value in values:
        start, end = value.split(",", 1)
        windows.append(Window(start.strip(), end.strip()))
    return windows


def build_url(base_url: str, source: str, window: Window) -> str:
    query = urllib.parse.urlencode(
        {"name": source, "starttime": window.start, "endtime": window.end}
    )
    return f"{base_url}?{query}"


def fetch_json(url: str, timeout: float) -> list[dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise TypeError(f"expected list payload, got {type(payload).__name__}")
    return [item for item in payload if isinstance(item, dict)]


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def classify(content: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if PRIVATE_NOISE_KEYWORDS.search(content):
        reasons.append("private_noise_keyword")
    if EVENT_KEYWORDS.search(content):
        reasons.append("event_keyword")
    if STOCK_KEYWORDS.search(content):
        reasons.append("stock_keyword")
    if RECOMMEND_KEYWORDS.search(content):
        reasons.append("recommend_keyword")
    if TICKER_PATTERN.search(content):
        reasons.append("ticker")
    if CHINESE_COMPANY_HINT.search(content):
        reasons.append("company_hint")

    if "private_noise_keyword" in reasons and "stock_keyword" not in reasons:
        return "noise_or_private", reasons
    if "event_keyword" in reasons and "recommend_keyword" not in reasons:
        return "event_or_activity", reasons
    if "recommend_keyword" in reasons and (
        "stock_keyword" in reasons or "ticker" in reasons or "company_hint" in reasons
    ):
        return "potential_recommendation", reasons
    if "stock_keyword" in reasons or "ticker" in reasons or "company_hint" in reasons:
        return "research_or_market_view", reasons
    return "unclear_or_noise", reasons


def analyze_record(source: str, window: Window, record: dict[str, Any]) -> dict[str, Any]:
    content = normalize_text(record.get("内容"))
    category, reasons = classify(content)
    return {
        "source": source,
        "window_start": window.start,
        "window_end": window.end,
        "time": record.get("时间", ""),
        "sender": record.get("发送人", ""),
        "group_name": record.get("群名称", ""),
        "category": category,
        "reasons": "|".join(reasons),
        "content_len": len(content),
        "tickers": "|".join(TICKER_PATTERN.findall(content)),
        "company_hints": "|".join(CHINESE_COMPANY_HINT.findall(content)[:10]),
        "content_preview": content[:180],
    }


def write_json(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_markdown_report(rows: list[dict[str, Any]], failures: list[str]) -> str:
    by_source_window: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source_window[(row["source"], row["window_start"], row["window_end"])].append(row)

    lines: list[str] = [
        "# 微信多时间窗口数据分析",
        "",
        "## 1. 样本概览",
        "",
        "| 来源 | 时间窗口 | 消息数 | 潜在推荐 | 研究观点 | 活动通知 | 噪声/不明确 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (source, start, end), items in sorted(by_source_window.items()):
        counter = Counter(item["category"] for item in items)
        lines.append(
            f"| {source} | {start} -> {end} | {len(items)} | "
            f"{counter['potential_recommendation']} | {counter['research_or_market_view']} | "
            f"{counter['event_or_activity']} | "
            f"{counter['noise_or_private'] + counter['unclear_or_noise']} |"
        )

    total_counter = Counter(row["category"] for row in rows)
    source_counter = Counter(row["source"] for row in rows)
    sender_counter = Counter(row["sender"] for row in rows if row["sender"])
    reason_counter = Counter(
        reason for row in rows for reason in str(row["reasons"]).split("|") if reason
    )

    lines += [
        "",
        "## 2. 总体分布",
        "",
        f"- 总消息数：{len(rows)}",
        f"- 个人消息：{source_counter.get('个人消息', 0)}",
        f"- 个人群：{source_counter.get('个人群', 0)}",
        f"- 潜在推荐：{total_counter['potential_recommendation']}",
        f"- 研究/市场观点：{total_counter['research_or_market_view']}",
        f"- 活动/调研通知：{total_counter['event_or_activity']}",
        f"- 噪声/不明确：{total_counter['noise_or_private'] + total_counter['unclear_or_noise']}",
        "",
        "## 3. 高频发送人",
        "",
        "| 发送人 | 消息数 |",
        "| --- | ---: |",
    ]
    for sender, count in sender_counter.most_common(15):
        lines.append(f"| {sender} | {count} |")

    lines += [
        "",
        "## 4. 规则命中特征",
        "",
        "| 特征 | 命中次数 |",
        "| --- | ---: |",
    ]
    for reason, count in reason_counter.most_common():
        lines.append(f"| {reason} | {count} |")

    lines += [
        "",
        "## 5. 代表性样本",
        "",
    ]
    for category in (
        "potential_recommendation",
        "research_or_market_view",
        "event_or_activity",
        "noise_or_private",
        "unclear_or_noise",
    ):
        lines += [f"### {category}", ""]
        samples = [row for row in rows if row["category"] == category][:5]
        for row in samples:
            lines.append(
                f"- `{row['source']}` `{row['time']}` `{row['sender']}`：{row['content_preview']}"
            )
        if not samples:
            lines.append("- 无")
        lines.append("")

    lines += [
        "## 6. 对模型精准度的启发",
        "",
        "1. 不能直接把“股票相关”当成“有效推荐”。很多内容是研报摘要、行业观点、会议活动，必须先做消息分类。",
        "2. 推荐抽取需要区分“明确推荐”和“泛研究观点”。例如“持续推荐”“重点关注”更接近推荐信号；单纯复盘、活动邀请不应进入胜率回测。",
        "3. 群消息量更大、噪声更多，需要更强的去噪和去重。个人消息相对更投研化，但仍有私人消息和活动通知。",
        "4. 发送人字段很关键，但需要身份归一。同一个人可能带券商、行业、emoji 或不同备注，后续要做 sender_normalized。",
        "5. 多标的消息会影响回测精准度。一条消息可能同时提到多个公司、行业和股票，不能简单按第一只股票回测。",
        "6. 原文中有 HTML 转义、emoji、换行和标签，结构化前必须统一清洗，否则会影响 LLM 抽取稳定性。",
        "7. 第一版模型建议采用“规则粗筛 + LLM 结构化抽取 + 人工可追溯复核”，不要完全依赖关键词。",
        "8. 胜率模型要只统计高置信有效推荐；研究观点和活动通知可进入热度分析，但不能进入推荐人胜率。",
        "",
    ]

    if failures:
        lines += ["## 7. 拉取失败", ""]
        lines.extend(f"- {failure}" for failure in failures)
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    report_dir = Path(args.report_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    windows = parse_windows(args.window)

    for window in windows:
        for source in SOURCES:
            url = build_url(args.base_url, source, window)
            raw_path = raw_dir / f"{source}_{window.label}.json"
            try:
                records = fetch_json(url, args.timeout)
            except Exception as exc:
                failures.append(f"{source} {window.start}->{window.end}: {type(exc).__name__}: {exc}")
                continue
            write_json(raw_path, records)
            rows.extend(analyze_record(source, window, record) for record in records)
            print(f"saved {raw_path} records={len(records)}")

    write_csv(report_dir / "wechat_windows_messages.csv", rows)
    markdown = build_markdown_report(rows, failures)
    (report_dir / "wechat_windows_analysis.md").write_text(markdown, encoding="utf-8")
    print(f"saved {report_dir / 'wechat_windows_messages.csv'} rows={len(rows)}")
    print(f"saved {report_dir / 'wechat_windows_analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
