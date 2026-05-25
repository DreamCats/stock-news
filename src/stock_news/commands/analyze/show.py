"""分析摘要展示：分类分布 + 推荐列表 + 观点链."""

from __future__ import annotations

import json

import click

from stock_news.commands.analyze._common import (
    load_classified,
    load_recommendations,
    opinion_dir,
    parse_date,
)
from stock_news.common.config import load
from stock_news.models import OpinionNode


def show_analysis(date_str: str, json_output: bool) -> None:
    cfg = load()
    dt = parse_date(date_str)

    classified = load_classified(cfg.storage.data_dir, dt)
    recs = load_recommendations(cfg.storage.data_dir, dt)

    opinions_path = opinion_dir(cfg.storage.data_dir, dt) / "opinions.json"
    opinions: list[OpinionNode] = []
    if opinions_path.exists():
        data = json.loads(opinions_path.read_text(encoding="utf-8"))
        opinions = [OpinionNode.model_validate(item) for item in data]

    if json_output:
        cat_counts: dict[str, int] = {}
        for c in classified:
            cat_counts[c.category.value] = cat_counts.get(c.category.value, 0) + 1
        click.echo(json.dumps({
            "ok": True,
            "data": {
                "date": dt.isoformat(),
                "classification": {"total": len(classified), "distribution": cat_counts},
                "recommendations": {"total": len(recs), "items": [r.model_dump(mode="json") for r in recs]},
                "opinions": {"total": len(opinions), "items": [o.model_dump(mode="json") for o in opinions]},
            },
            "message": f"{dt} 分析摘要",
        }, ensure_ascii=False, indent=2))
    else:
        click.echo(f"=== {dt} 分析摘要 ===\n")

        if classified:
            cat_counts = {}
            for c in classified:
                cat_counts[c.category.value] = cat_counts.get(c.category.value, 0) + 1
            click.echo(f"消息分类 ({len(classified)} 条):")
            for cat, cnt in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
                click.echo(f"  {cat}: {cnt} 条")
        else:
            click.echo("消息分类: 未运行")

        click.echo()

        if recs:
            click.echo(f"结构化推荐 ({len(recs)} 条):")
            for r in recs:
                click.echo(f"  [{r.action}][{r.strength}] {r.ticker} - {r.sender}")
        else:
            click.echo("结构化推荐: 未运行")

        click.echo()

        if opinions:
            click.echo(f"观点链 ({len(opinions)} 条):")
            for o in opinions:
                click.echo(f"  [{o.update_type}][{o.stance}] {o.sender} -> {o.topic_key}: {o.summary}")
        else:
            click.echo("观点链: 未运行")
