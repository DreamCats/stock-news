"""公开研究源每日摘要 HTML 渲染。

这里生成适配移动端的单页 HTML，供 Aly 静态发布。
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from stock_news.usecases.research.models import (
    ResearchBriefDocument,
    ResearchBriefSummary,
)


def render_research_daily_brief_html(
    *,
    summary: ResearchBriefSummary,
    documents: list[ResearchBriefDocument],
    generated_at: datetime,
) -> str:
    """渲染公开研究源每日摘要 HTML。"""

    title = escape(summary.title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --ink: #16181d;
      --muted: #626a77;
      --line: #dfe3ea;
      --panel: #ffffff;
      --accent: #0f7a6d;
      --accent-soft: #e7f4f1;
      --warn: #8a5a00;
      --warn-soft: #fff4d8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.6;
    }}
    main {{
      width: min(920px, 100%);
      margin: 0 auto;
      padding: 20px 14px 36px;
    }}
    header {{
      padding: 10px 0 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 28px;
      line-height: 1.18;
      letter-spacing: 0;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .summary {{
      margin: 18px 0;
      padding: 14px;
      background: var(--accent-soft);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      font-size: 16px;
    }}
    section {{ margin-top: 22px; }}
    h2 {{
      margin: 0 0 10px;
      font-size: 19px;
      letter-spacing: 0;
    }}
    .theme, .item, .source {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 10px;
    }}
    .theme strong, .item h3 {{
      display: block;
      margin: 0 0 6px;
      font-size: 16px;
      line-height: 1.35;
    }}
    .theme p, .item p, .source p {{
      margin: 0;
      color: var(--muted);
    }}
    .item .byline {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    ul {{
      margin: 10px 0 0;
      padding-left: 20px;
      color: var(--muted);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty {{
      background: var(--warn-soft);
      border-color: #f0d28a;
      color: var(--warn);
    }}
    @media (max-width: 520px) {{
      main {{ padding: 16px 12px 28px; }}
      h1 {{ font-size: 24px; }}
      .summary, .theme, .item, .source {{ border-radius: 7px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{title}</h1>
      <div class="meta">
        <span>生成时间：{escape(_format_dt(generated_at))}</span>
        <span>统计窗口：近 48 小时</span>
        <span>研究内容：{len(documents)} 条</span>
      </div>
    </header>
    <div class="summary">{escape(summary.summary)}</div>
    {_render_themes(summary)}
    {_render_items(summary)}
    {_render_sources(documents)}
  </main>
</body>
</html>
"""


def _render_themes(summary: ResearchBriefSummary) -> str:
    if not summary.themes:
        return ""
    rows = "\n".join(
        '<div class="theme">'
        f"<strong>{escape(item.name)}</strong>"
        f"<p>{escape(item.description)}</p>"
        "</div>"
        for item in summary.themes
    )
    return f"<section><h2>主线</h2>{rows}</section>"


def _render_items(summary: ResearchBriefSummary) -> str:
    if not summary.items:
        return (
            "<section><h2>重点内容</h2>"
            '<div class="item empty">暂无可展示的重点内容。</div></section>'
        )
    rows = "\n".join(
        '<article class="item">'
        f"<h3>{index}. {escape(item.title)}</h3>"
        f'<div class="byline">{escape(item.source_name)} · '
        f"{escape(item.published_at or '-')}</div>"
        f"<p>{escape(item.reason)}</p>"
        f"{_render_points(item.key_points)}"
        f'<p><a href="{escape(item.url)}">查看原文</a></p>'
        "</article>"
        for index, item in enumerate(summary.items, start=1)
    )
    return f"<section><h2>重点内容</h2>{rows}</section>"


def _render_points(points: tuple[str, ...]) -> str:
    if not points:
        return ""
    rows = "".join(f"<li>{escape(item)}</li>" for item in points)
    return f"<ul>{rows}</ul>"


def _render_sources(documents: list[ResearchBriefDocument]) -> str:
    if not documents:
        return ""
    rows = "\n".join(
        '<div class="source">'
        f"<p>{escape(item.source_name)} · {escape(item.published_at or '-')}</p>"
        f'<p><a href="{escape(item.url)}">{escape(item.title)}</a></p>'
        "</div>"
        for item in documents
    )
    return f"<section><h2>本次抓取</h2>{rows}</section>"


def _format_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")
