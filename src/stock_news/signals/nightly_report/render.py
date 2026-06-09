"""每日晚报 HTML 渲染."""

from __future__ import annotations

from html import escape
from typing import Any

from stock_news.signals.nightly_report.time import display_dt


def render_nightly_html(payload: dict[str, Any]) -> str:
    """渲染适合手机扫读的晚报 HTML."""
    window = payload.get("window") or {}
    start = display_dt(str(window.get("start") or ""))
    end = display_dt(str(window.get("end") or ""))
    items = payload.get("items") or []
    generated_at = display_dt(str(payload.get("generated_at") or ""))
    rows = []
    for item in items:
        name = escape(str(item.get("target_name") or "-"))
        brief = escape(str(item.get("brief") or "-"))
        rows.append(
            f"""
            <li>
              <div class="line">
                <span class="dash">-</span><strong>{name}</strong>：{brief}
              </div>
            </li>
            """
        )
    if not rows:
        rows.append('<li><div class="line">本窗口暂无可进入晚报的股票推荐。</div></li>')

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日投研晚报</title>
  <style>
    :root {{
      color: #1f2933;
      background: #f7f8fa;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body {{
      margin: 0;
      background: #f7f8fa;
    }}
    main {{
      max-width: 760px;
      margin: 0 auto;
      padding: 24px 18px 36px;
      background: #ffffff;
      min-height: 100vh;
      box-sizing: border-box;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.25;
    }}
    .sub {{
      margin: 0 0 22px;
      color: #667085;
      font-size: 13px;
      line-height: 1.6;
    }}
    ul {{
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    li {{
      padding: 4px 0;
    }}
    .line {{
      font-size: 18px;
      line-height: 1.48;
      font-weight: 560;
    }}
    .dash {{
      display: inline-block;
      width: 18px;
      font-weight: 700;
    }}
    footer {{
      margin-top: 22px;
      color: #98a2b3;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>每日投研晚报</h1>
    <p class="sub">
      窗口：{escape(start)} - {escape(end)}；生成：{escape(generated_at)}
    </p>
    <ul>
      {"".join(rows)}
    </ul>
    <footer>仅基于本地 recommend 结构化数据生成，不构成投资建议。</footer>
  </main>
</body>
</html>
"""
