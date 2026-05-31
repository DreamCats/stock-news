"""策略快报 Markdown 渲染."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .utils import _cell, _pct, _unique_texts


def _render_markdown(payload: dict[str, Any]) -> str:
    report_time = datetime.fromisoformat(str(payload["report_time"]))
    lines = [f"# 盘中投研快报 {report_time.strftime('%H:%M')}", ""]

    candidates = payload["candidate_trades"]
    lines.append("## 推荐个股")
    lines.append("| 标的 | Score | 推荐人 | 核心证据 |")
    lines.append("| --- | ---: | --- | --- |")
    for item in candidates:
        senders = "、".join(item["senders"][:5])
        if len(item["senders"]) > 5:
            senders += f" 等{len(item['senders'])}人"
        clue = "；".join(_unique_texts(item["evidences"] or item["reasons"], limit=2))
        clue = clue or "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(item["target_name"]),
                    _cell(item["score"]),
                    _cell(senders),
                    _cell(clue),
                ]
            )
            + " |"
        )
    if not candidates:
        lines.append("| - | - | - | 本轮无新增可交易个股 |")

    lines.extend(["", "## 推荐人可信度"])
    lines.append("| 推荐人 | 胜率 | 样本数 | 最近命中样本 |")
    lines.append("| --- | ---: | ---: | --- |")
    if payload["sender_credibility"]:
        for item in payload["sender_credibility"]:
            samples = "、".join(item.get("samples") or []) or "-"
            sender = str(item["sender"])
            if item.get("whitelisted"):
                sender = f"{sender}（白名单）"
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(sender),
                        _pct(item.get("win_rate_t5")),
                        _cell(item.get("count")),
                        _cell(samples),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | - | 本轮涉及推荐人暂无满足阈值的回测样本 |")

    return "\n".join(lines) + "\n"
