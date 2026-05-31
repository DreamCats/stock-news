"""盘中策略快报生成入口."""

from __future__ import annotations

import json
from datetime import datetime

import click

from stock_news.common.config import load
from stock_news.models import StrategyConfig

from .llm import _attach_candidate_logic
from .payload import _build_payload
from .render import _render_markdown
from .storage import _save_outputs


def generate(
    date_str: str,
    window_minutes: int,
    top: int,
    json_output: bool,
    use_llm: bool = False,
    provider_name: str | None = None,
) -> None:
    """生成盘中策略快报 JSON 和 Markdown."""
    cfg = load()
    report_time = datetime.now().replace(microsecond=0)
    payload, state = _build_payload(
        cfg.storage.data_dir,
        date_str,
        window_minutes,
        top,
        report_time,
        getattr(cfg, "strategy", StrategyConfig()),
    )
    _attach_candidate_logic(payload, use_llm, provider_name)
    markdown = _render_markdown(payload)
    json_path, md_path = _save_outputs(
        cfg.storage.data_dir,
        payload["date"],
        payload,
        markdown,
        state,
    )

    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "date": payload["date"],
                        "has_updates": payload["has_updates"],
                        "json_path": str(json_path),
                        "markdown_path": str(md_path),
                    },
                },
                ensure_ascii=False,
            )
        )
    else:
        click.echo(f"策略快报已生成: {md_path}")
        if not payload["has_updates"]:
            click.echo("本轮无新增有效机会。")
