"""生成分析报告 HTML."""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any

import click

from stock_news.common.config import load
from stock_news.common.storage import load_messages
from stock_news.models import (
    ClassifiedMessage,
    OpinionNode,
    Recommendation,
)


def _parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def _load_classified(cfg_data_dir: str, dt: date) -> list[ClassifiedMessage]:
    path = Path(cfg_data_dir).expanduser() / dt.isoformat() / "classified" / "classified.json"
    if not path.exists():
        return []
    return [ClassifiedMessage.model_validate(i) for i in json.loads(path.read_text(encoding="utf-8"))]


def _load_recommendations(cfg_data_dir: str, dt: date) -> list[Recommendation]:
    path = Path(cfg_data_dir).expanduser() / dt.isoformat() / "extracted" / "recommendations.json"
    if not path.exists():
        return []
    return [Recommendation.model_validate(i) for i in json.loads(path.read_text(encoding="utf-8"))]


def _load_opinions(cfg_data_dir: str, dt: date) -> list[OpinionNode]:
    path = Path(cfg_data_dir).expanduser() / dt.isoformat() / "opinions" / "opinions.json"
    if not path.exists():
        return []
    return [OpinionNode.model_validate(i) for i in json.loads(path.read_text(encoding="utf-8"))]


def _load_sender_stats(cfg_data_dir: str) -> dict[str, dict[str, Any]]:
    path = Path(cfg_data_dir).expanduser() / "backtest_summary" / "sender_stats.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["sender"]: s for s in data if isinstance(s, dict) and s.get("sender")}


_WINRATE_MIN_COUNT = 10


def _winrate_chip(sender: str, stats: dict[str, dict[str, Any]]) -> str:
    s = stats.get(sender)
    if not s or int(s.get("count", 0)) < _WINRATE_MIN_COUNT:
        return '<span class="who-winrate wr-na">样本不足</span>'
    wr = float(s.get("win_rate_t5") or 0)
    n = int(s.get("count", 0))
    if wr >= 0.70:
        tier = "wr-gold"
    elif wr >= 0.55:
        tier = "wr-silver"
    else:
        tier = "wr-bronze"
    pct = f"{wr*100:.0f}"
    return (
        f'<span class="who-winrate {tier}" '
        f'title="T+5 胜率 {pct}%，{n} 条历史样本">'
        f'{pct}% / {n}</span>'
    )


def _e(t: str) -> str:
    return escape(str(t))


def _highlight(text: str) -> str:
    """将 **关键词** 转为高亮 HTML span."""
    import re
    safe = escape(text)
    return re.sub(
        r'\*\*(.+?)\*\*',
        r'<span class="hl">\1</span>',
        safe,
    )


_ACTION_COLOR = {
    "买入": "#16a34a", "加仓": "#15803d", "关注": "#2563eb",
    "减仓": "#d97706", "卖出": "#dc2626",
}


# -- LLM 调用 --


def _llm_summary(recs: list[Recommendation], opinions: list[OpinionNode], provider_name: str | None) -> str:
    from stock_news.common.llm.client import chat, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("report")

    # 构造精简的推荐摘要
    rec_lines: list[str] = []
    for r in recs:
        rec_lines.append(f"[{r.action}][{r.strength}] {r.ticker} - {r.sender}: {r.reasoning or ''}")
    rec_text = "\n".join(rec_lines[:80])

    # 构造精简的观点摘要（去重后）
    seen: dict[tuple[str, str], OpinionNode] = {}
    for o in opinions:
        seen[(o.sender, o.topic_key)] = o
    op_lines = [f"[{o.update_type}][{o.stance}] {o.sender} -> {o.topic_key}: {o.summary}" for o in seen.values()]
    op_text = "\n".join(op_lines[:50])

    prompt = render_prompt("report_summary", recommendations=rec_text, opinions=op_text)
    try:
        return chat([{"role": "user", "content": prompt}], provider_name=provider_name)
    except Exception as e:
        return f"(摘要生成失败: {e})"


def _llm_ticker_logic(ticker: str, items: list[Recommendation], provider_name: str | None) -> str:
    from stock_news.common.llm.client import chat, get_provider_for_task
    from stock_news.common.llm.prompts import render_prompt

    if not provider_name:
        provider_name, _ = get_provider_for_task("report")

    details_lines: list[str] = []
    for r in items:
        details_lines.append(f"- {r.sender}（{r.action}/{r.strength}）: {r.reasoning or '无明确理由'}")
    details = "\n".join(details_lines)

    prompt = render_prompt("report_logic", ticker=ticker, details=details)
    try:
        return chat([{"role": "user", "content": prompt}], provider_name=provider_name)
    except Exception:
        # fallback: 拼接原始 reasoning
        reasons = list({r.reasoning for r in items if r.reasoning})
        return "；".join(reasons[:3]) if reasons else "暂无明确逻辑"


def _generate_llm_content(
    recs: list[Recommendation],
    opinions: list[OpinionNode],
    provider_name: str | None,
    json_output: bool,
) -> tuple[str, dict[str, str]]:
    """并行生成：全局摘要 + 每个 ticker 的逻辑归纳."""
    from stock_news.common.llm.prompts import ensure_prompts_dir
    ensure_prompts_dir()

    # 按 ticker 分组
    ticker_recs: dict[str, list[Recommendation]] = defaultdict(list)
    for r in recs:
        ticker_recs[r.ticker].append(r)

    if not json_output:
        click.echo(f"  LLM 生成中: 1 篇摘要 + {len(ticker_recs)} 个标的逻辑...", err=True)

    summary = ""
    ticker_logic: dict[str, str] = {}

    CONCURRENCY = 10

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        # 提交全局摘要
        summary_future = pool.submit(_llm_summary, recs, opinions, provider_name)

        # 提交每个 ticker 的逻辑归纳
        logic_futures = {
            pool.submit(_llm_ticker_logic, ticker, items, provider_name): ticker
            for ticker, items in ticker_recs.items()
        }

        # 收集结果
        summary = summary_future.result()

        done_count = 0
        for future in as_completed(logic_futures):
            ticker = logic_futures[future]
            ticker_logic[ticker] = future.result()
            done_count += 1
            if not json_output and done_count % 10 == 0:
                click.echo(f"  已完成 {done_count}/{len(ticker_recs)} 个标的...", err=True)

    if not json_output:
        click.echo(f"  LLM 内容生成完成", err=True)

    return summary, ticker_logic


# -- HTML 构建 --


def _build_ticker_cards(
    recs: list[Recommendation],
    ticker_logic: dict[str, str],
    sender_stats: dict[str, dict[str, Any]],
) -> str:
    ticker_recs: dict[str, list[Recommendation]] = defaultdict(list)
    for r in recs:
        ticker_recs[r.ticker].append(r)

    action_rank = {"买入": 5, "加仓": 4, "关注": 3, "减仓": 2, "卖出": 1}

    cards_data: list[dict] = []
    for ticker, items in ticker_recs.items():
        sender_set: dict[str, Recommendation] = {}
        for r in items:
            if r.sender not in sender_set:
                sender_set[r.sender] = r
        best_action = max(items, key=lambda r: action_rank.get(r.action, 0)).action
        cards_data.append({
            "ticker": ticker,
            "n_senders": len(sender_set),
            "senders": sender_set,
            "best_action": best_action,
        })

    cards_data.sort(key=lambda d: (d["n_senders"], action_rank.get(d["best_action"], 0)), reverse=True)

    bullish = [d for d in cards_data if d["best_action"] not in ("卖出", "减仓")]
    bearish = [d for d in cards_data if d["best_action"] in ("卖出", "减仓")]

    def _render(cards: list[dict]) -> str:
        html = ""
        for d in cards:
            ticker = d["ticker"]
            n = d["n_senders"]

            if n >= 3:
                cls, label = "hot-3", f"🔥 {n} 人共推"
            elif n >= 2:
                cls, label = "hot-2", f"{n} 人推荐"
            else:
                cls, label = "", ""

            logic = ticker_logic.get(ticker, "暂无明确逻辑")
            logic_html = f'<div class="logic-text">{_e(logic)}</div>'

            senders_html = ""
            for sender, r in d["senders"].items():
                ac = _ACTION_COLOR.get(r.action, "#6b7280")
                senders_html += (
                    f'<div class="who-row">'
                    f'<span class="who-action" style="color:{ac}">{_e(r.action)}</span>'
                    f'<span class="who-strength">{_e(r.strength)}</span>'
                    f'<span class="who-name">{_e(sender)}</span>'
                    f'{_winrate_chip(sender, sender_stats)}'
                    f'</div>'
                )

            html += (
                f'<div class="ticker-card {cls}">'
                f'<div class="ticker-header">'
                f'<span class="ticker-name">{_e(ticker)}</span>'
                f'{f"""<span class="consensus-badge">{label}</span>""" if label else ""}'
                f'</div>'
                f'<div class="ticker-logic">'
                f'<div class="sub-title">投资逻辑</div>'
                f'{logic_html}'
                f'</div>'
                f'<div class="ticker-who">'
                f'<div class="sub-title">推荐人</div>'
                f'{senders_html}'
                f'</div>'
                f'</div>'
            )
        return html

    result = ""
    if bearish:
        result += '<div class="signal-group">'
        result += '<div class="signal-group-title risk-title">⚠ 风险信号</div>'
        result += _render(bearish)
        result += '</div>'
    if bullish:
        result += '<div class="signal-group">'
        result += '<div class="signal-group-title">看多标的</div>'
        result += _render(bullish)
        result += '</div>'

    return result or '<div class="empty-note">暂无推荐数据</div>'


def _build_opinion_summary(opinions: list[OpinionNode]) -> str:
    _update_label = {
        "new": "新观点", "reinforce": "强化", "supplement": "补充",
        "revise": "修正", "reverse": "反转", "withdraw": "撤回",
    }
    _update_color = {
        "new": "#2563eb", "reinforce": "#16a34a", "supplement": "#0891b2",
        "revise": "#d97706", "reverse": "#dc2626", "withdraw": "#6b7280",
    }
    _stance_label = {"bullish": "看多", "bearish": "看空", "neutral": "中性", "mixed": "分歧"}
    _stance_color = {"bullish": "#16a34a", "bearish": "#dc2626", "neutral": "#64748b", "mixed": "#d97706"}

    sender_ops: dict[str, dict[str, OpinionNode]] = defaultdict(dict)
    for o in opinions:
        sender_ops[o.sender][o.topic_key] = o

    change_weight = {"reverse": 5, "withdraw": 4, "revise": 3, "new": 2, "supplement": 1, "reinforce": 0}

    def sender_score(s: str) -> int:
        return max(change_weight.get(o.update_type, 0) for o in sender_ops[s].values())

    html = ""
    for sender in sorted(sender_ops, key=sender_score, reverse=True):
        topics = sender_ops[sender]
        rows = ""
        for topic, o in topics.items():
            u_label = _update_label.get(o.update_type, o.update_type)
            u_color = _update_color.get(o.update_type, "#666")
            s_label = _stance_label.get(o.stance, o.stance)
            s_color = _stance_color.get(o.stance, "#666")
            rows += (
                f'<div class="op-row">'
                f'<span class="op-badge" style="color:{u_color}">{_e(u_label)}</span>'
                f'<span class="op-stance" style="color:{s_color}">{_e(s_label)}</span>'
                f'<span class="op-topic">{_e(topic)}</span>'
                f'<span class="op-summary">{_e(o.summary)}</span>'
                f'</div>'
            )
        html += f'<div class="op-sender"><div class="op-sender-name">{_e(sender)}</div>{rows}</div>'
    return html or '<div class="empty-note">暂无观点数据</div>'


def _render_html(
    dt: date,
    classified: list[ClassifiedMessage],
    recs: list[Recommendation],
    opinions: list[OpinionNode],
    total_messages: int,
    summary: str,
    ticker_logic: dict[str, str],
    sender_stats: dict[str, dict[str, Any]],
) -> str:
    n_tickers = len(set(r.ticker for r in recs))
    n_senders = len(set(r.sender for r in recs))

    summary_html = _highlight(summary).replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>投研日报 {dt.isoformat()}</title>
<style>
:root {{
  --bg: #fafafa; --surface: #fff; --border: #eaeaea;
  --text-1: #111; --text-2: #555; --text-3: #999;
  --accent: #2563eb; --green: #16a34a; --red: #dc2626; --orange: #d97706;
  --r: 8px;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue",
    "PingFang SC", "Noto Sans CJK SC", sans-serif;
  background: var(--bg); color: var(--text-1); line-height: 1.65;
  -webkit-font-smoothing: antialiased; font-size: 14px;
}}
.wrap {{ max-width: 800px; margin: 0 auto; padding: 48px 20px 80px; }}

.header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }}
.header h1 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
.header .date {{ font-size: 13px; color: var(--text-3); }}
.sub-stats {{ font-size: 13px; color: var(--text-3); margin-bottom: 28px; }}
.sub-stats strong {{ color: var(--text-1); font-weight: 600; }}

/* Summary */
.summary-box {{
  background: linear-gradient(135deg, #f0f7ff, #faf5ff);
  border: 1px solid #e0e7ff;
  border-radius: var(--r); padding: 18px 20px;
  margin-bottom: 36px; font-size: 14px; line-height: 1.8; color: var(--text-1);
}}

.section {{ margin-bottom: 40px; }}
.section-title {{
  font-size: 13px; font-weight: 700; color: var(--text-2);
  text-transform: uppercase; letter-spacing: 1.5px;
  margin-bottom: 14px;
}}

/* Ticker Cards */
.signal-group {{ margin-bottom: 28px; }}
.signal-group-title {{ font-size: 15px; font-weight: 700; margin-bottom: 10px; padding-left: 2px; }}
.risk-title {{ color: var(--red); }}

.ticker-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r); margin-bottom: 10px; overflow: hidden;
  transition: box-shadow .15s;
}}
.ticker-card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,.04); }}
.ticker-card.hot-3 {{ border-left: 3px solid var(--red); }}
.ticker-card.hot-2 {{ border-left: 3px solid var(--accent); }}

.ticker-header {{
  display: flex; align-items: center; gap: 10px; padding: 12px 16px 0;
}}
.ticker-name {{ font-size: 17px; font-weight: 700; }}
.consensus-badge {{
  font-size: 11px; font-weight: 600; color: var(--accent);
  background: #eff6ff; padding: 2px 8px; border-radius: 10px;
}}
.ticker-card.hot-3 .consensus-badge {{ color: var(--red); background: #fef2f2; }}

.ticker-logic {{ padding: 8px 16px 4px; }}
.ticker-who {{ padding: 6px 16px 12px; }}
.sub-title {{ font-size: 11px; color: var(--text-3); font-weight: 600; letter-spacing: 0.5px; margin-bottom: 4px; }}
.logic-text {{ font-size: 13px; color: var(--text-2); line-height: 1.7; }}

.who-row {{ display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 13px; }}
.who-action {{ font-weight: 700; width: 28px; flex-shrink: 0; }}
.who-strength {{ font-size: 11px; color: var(--text-3); width: 16px; flex-shrink: 0; }}
.who-name {{
  color: var(--text-2); flex: 1; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.who-winrate {{
  font-size: 11px; padding: 1px 6px; border-radius: 4px;
  font-weight: 600; flex-shrink: 0; letter-spacing: 0.2px;
}}
.wr-gold {{ background: #fef3c7; color: #92400e; }}
.wr-silver {{ background: #e0f2fe; color: #0369a1; }}
.wr-bronze {{ background: #f5f5f4; color: #78716c; }}
.wr-na {{ background: transparent; color: var(--text-3); font-weight: 400; font-size: 10px; }}

/* Opinion */
.op-sender {{ margin-bottom: 14px; }}
.op-sender-name {{ font-size: 13px; font-weight: 600; margin-bottom: 4px; padding-left: 2px; }}
.op-row {{
  display: flex; align-items: baseline; gap: 6px; padding: 3px 0 3px 12px;
  font-size: 13px; border-left: 2px solid var(--border);
}}
.op-badge {{ font-weight: 700; font-size: 12px; flex-shrink: 0; width: 40px; }}
.op-stance {{ font-size: 12px; font-weight: 600; flex-shrink: 0; width: 28px; }}
.op-topic {{ font-weight: 600; color: var(--text-1); flex-shrink: 0; }}
.op-summary {{ color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

.hl {{
  color: #1d4ed8; font-weight: 700;
  background: linear-gradient(transparent 60%, #bfdbfe 60%);
  padding: 0 2px;
}}

.empty-note {{ font-size: 13px; color: var(--text-3); padding: 8px 0; }}
.sep {{ height: 1px; background: var(--border); margin: 36px 0; }}

footer {{
  text-align: center; font-size: 11px; color: var(--text-3);
  margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--border);
}}
</style>
</head>
<body>
<div class="wrap">

<div class="header">
  <h1>投研日报</h1>
  <span class="date">{dt.isoformat()}</span>
</div>
<div class="sub-stats">
  <strong>{len(recs)}</strong> 条推荐 · <strong>{n_tickers}</strong> 个标的 · <strong>{n_senders}</strong> 位推荐人 · 来自 <strong>{total_messages}</strong> 条原始消息
</div>

<div class="summary-box">
  {summary_html}
</div>

<div class="section">
  <div class="section-title">标的与逻辑</div>
  {_build_ticker_cards(recs, ticker_logic, sender_stats)}
</div>

<div class="sep"></div>

<div class="section">
  <div class="section-title">观点变化</div>
  {_build_opinion_summary(opinions)}
</div>

<footer>stock-news CLI · sn analyze report</footer>

</div>
</body>
</html>"""


def generate_report(date_str: str, output: str | None, provider_name: str | None, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)

    classified = _load_classified(cfg.storage.data_dir, dt)
    recs = _load_recommendations(cfg.storage.data_dir, dt)
    opinions = _load_opinions(cfg.storage.data_dir, dt)
    messages = load_messages(cfg.storage.data_dir, dt)
    sender_stats = _load_sender_stats(cfg.storage.data_dir)

    if not classified and not recs:
        click.echo(f"{dt} 无分析数据，请先运行: sn analyze classify / extract / opinion")
        return

    summary, ticker_logic = _generate_llm_content(recs, opinions, provider_name, json_output)

    html = _render_html(
        dt, classified, recs, opinions, len(messages),
        summary, ticker_logic, sender_stats,
    )

    if output:
        out_path = Path(output).expanduser()
    else:
        report_dir = Path(cfg.storage.data_dir).expanduser() / dt.isoformat() / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / "daily-report.html"

    out_path.write_text(html, encoding="utf-8")
    click.echo(f"报告已生成: {out_path}")
