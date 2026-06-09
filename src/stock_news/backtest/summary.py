"""推荐人回测汇总."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from stock_news.backtest.constants import WINDOWS


def aggregate_by_sender(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sender: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_sender[row["sender"]].append(row)

    stats: list[dict[str, Any]] = []
    for sender, items in by_sender.items():
        item_stats: dict[str, object] = {"sender": sender, "count": len(items)}
        for window in WINDOWS:
            wins = [
                row[f"win_t{window}"]
                for row in items
                if isinstance(row.get(f"win_t{window}"), bool)
            ]
            rets = [
                row[f"ret_t{window}"]
                for row in items
                if isinstance(row.get(f"ret_t{window}"), int | float)
            ]
            excess = [
                row[f"excess_t{window}"]
                for row in items
                if isinstance(row.get(f"excess_t{window}"), int | float)
            ]
            if wins and rets:
                item_stats[f"win_rate_t{window}"] = round(sum(wins) / len(wins), 4)
                item_stats[f"avg_ret_t{window}"] = round(sum(rets) / len(rets), 6)
            if excess:
                item_stats[f"avg_excess_t{window}"] = round(
                    sum(excess) / len(excess),
                    6,
                )
        stats.append(item_stats)

    stats.sort(
        key=lambda row: (row.get("win_rate_t5") or 0, row.get("count", 0)),
        reverse=True,
    )
    return stats
