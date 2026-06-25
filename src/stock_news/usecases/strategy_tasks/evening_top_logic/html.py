"""晚间 Top 投研逻辑 HTML 渲染。

这里生成适合移动端阅读的静态 HTML，不依赖前端构建工具。
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from stock_news.core.wechat import TimeWindow
from stock_news.usecases.strategy_tasks.evening_top_logic.models import (
    EveningLLMSelection,
    EveningLogicItem,
)


def render_evening_top_logic_html(
    *,
    selection: EveningLLMSelection,
    window: TimeWindow,
    generated_at: datetime,
) -> str:
    """渲染晚间 Top 投研逻辑 HTML。"""

    date = window.end.date().isoformat()
    body = "\n".join(_render_item(item) for item in selection.items)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>今晚值得重点看的 {len(selection.items)} 条投研逻辑</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --ink: #111827;
      --muted: #667085;
      --line: #d9dee7;
      --panel: #ffffff;
      --accent: #0f766e;
      --accent-soft: #e6f4f1;
      --warn-soft: #fff3d6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.58;
    }}
    main {{
      width: min(920px, 100%);
      margin: 0 auto;
      padding: 22px 14px 36px;
    }}
    header {{
      padding: 8px 2px 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: clamp(24px, 8vw, 36px);
      line-height: 1.15;
      letter-spacing: 0;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel);
    }}
    .summary {{
      margin: 18px 0 0;
      padding: 12px 14px;
      border-left: 4px solid var(--accent);
      background: var(--accent-soft);
      border-radius: 6px;
      font-size: 15px;
    }}
    .item {{
      margin-top: 14px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .item-head {{
      display: grid;
      grid-template-columns: 42px 1fr;
      gap: 10px;
      align-items: start;
    }}
    .rank {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: var(--ink);
      color: #fff;
      font-weight: 700;
      font-size: 14px;
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.35;
      letter-spacing: 0;
    }}
    .stock {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 13px;
    }}
    .reason {{
      margin: 12px 0 0;
      font-size: 15px;
    }}
    .llm-evidence {{
      margin-top: 12px;
      padding: 10px 12px;
      border-left: 3px solid var(--accent);
      background: #fbfcfe;
      border-radius: 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .llm-evidence strong {{
      color: var(--ink);
    }}
    .tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 12px;
    }}
    .tag {{
      padding: 2px 7px;
      border-radius: 999px;
      background: var(--warn-soft);
      color: #7a4b00;
      font-size: 12px;
      white-space: nowrap;
    }}
    .evidence {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .evidence div {{
      min-width: 0;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
      font-size: 12px;
      color: var(--muted);
    }}
    .evidence strong {{
      display: block;
      color: var(--ink);
      font-size: 16px;
      line-height: 1.2;
    }}
    footer {{
      margin-top: 22px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}
    @media (max-width: 640px) {{
      main {{ padding: 18px 12px 28px; }}
      .item {{ padding: 12px; }}
      .evidence {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>今晚值得重点看的 {len(selection.items)} 条投研逻辑</h1>
      <div class="meta">
        <span class="pill">{escape(date)}</span>
        <span class="pill">{escape(_format_window(window))}</span>
        <span class="pill">生成于 {escape(generated_at.strftime("%H:%M"))}</span>
      </div>
      <p class="summary">{escape(selection.summary)}</p>
    </header>
    <section>
      {body}
    </section>
    <footer>由 stock-news 根据微信消息催化词、标的聚合和 LLM 精选生成。</footer>
  </main>
</body>
</html>
"""


def _render_item(item: EveningLogicItem) -> str:
    candidate = item.candidate
    tags = "".join(
        f'<span class="tag">{escape(tag)}</span>' for tag in item.key_catalysts
    )
    return f"""
<article class="item">
  <div class="item-head">
    <span class="rank">{item.rank}</span>
    <div>
      <h2>{escape(item.title)}</h2>
      <div class="stock">{escape(candidate.stock.label)}</div>
    </div>
  </div>
  <p class="reason">{escape(item.reason)}</p>
  <div class="llm-evidence">
    <strong>证据组织：</strong>{escape(item.evidence_description)}
  </div>
  <div class="tags">{tags}</div>
  <div class="evidence">
    <div><strong>{candidate.score:g}</strong>强度分</div>
    <div><strong>{candidate.message_count}</strong>命中消息</div>
    <div><strong>{candidate.cluster_count}</strong>内容簇</div>
    <div><strong>{len(candidate.senders)}</strong>独立发送人</div>
  </div>
</article>
"""


def _format_window(window: TimeWindow) -> str:
    return f"{window.start.strftime('%H:%M')} - {window.end.strftime('%H:%M')}"
