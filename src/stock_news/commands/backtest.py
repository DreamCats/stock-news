"""推荐人胜率回测."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import click

from stock_news.common.config import load
from stock_news.models import Recommendation

WINDOWS = [1, 2, 3, 5, 10]
BENCHMARK = "000300.SH"


def _parse_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    if date_str == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(date_str)


def _load_recommendations(data_dir: str, dt: date) -> list[Recommendation]:
    path = Path(data_dir).expanduser() / dt.isoformat() / "extracted" / "recommendations.json"
    if not path.exists():
        return []
    return [Recommendation.model_validate(i) for i in json.loads(path.read_text(encoding="utf-8"))]


def _resolve_ticker(name: str) -> str | None:
    """股票名称 → ts_code，匹配不上返回 None."""
    from stock_news.common.market.db import get_ts_code
    return get_ts_code(name)


def _is_bullish(action: str) -> bool:
    return action in ("买入", "加仓", "关注")


def _backtest_one(
    rec: Recommendation,
    ts_code: str,
    rec_date: str,
) -> dict | None:
    """对单条推荐做回测，返回各窗口收益率."""
    from stock_news.common.market.db import get_next_n_trade_dates
    from stock_news.common.market.tushare_client import fetch_daily, fetch_index_daily

    rec_dt = date(int(rec_date[:4]), int(rec_date[4:6]), int(rec_date[6:8]))
    base_rows = fetch_daily(ts_code, rec_date, rec_date)
    if not base_rows:
        start_minus = (rec_dt - timedelta(days=5)).strftime("%Y%m%d")
        base_rows = fetch_daily(ts_code, start_minus, rec_date)
        if not base_rows:
            return None
    base_close = base_rows[-1]["close"]

    future_dates = get_next_n_trade_dates(rec_dt, max(WINDOWS))
    if not future_dates:
        return None

    end_date = future_dates[-1]
    future_rows = fetch_daily(ts_code, future_dates[0], end_date)
    price_map = {r["trade_date"]: r["close"] for r in future_rows}

    bench_base_rows = fetch_index_daily(BENCHMARK, rec_date, rec_date)
    if not bench_base_rows:
        start_minus = (rec_dt - timedelta(days=5)).strftime("%Y%m%d")
        bench_base_rows = fetch_index_daily(BENCHMARK, start_minus, rec_date)
    bench_base = bench_base_rows[-1]["close"] if bench_base_rows else None

    bench_rows = fetch_index_daily(BENCHMARK, future_dates[0], end_date) if bench_base else []
    bench_map = {r["trade_date"]: r["close"] for r in bench_rows}

    bullish = _is_bullish(rec.action)
    results: dict[str, object] = {
        "ts_code": ts_code,
        "ticker": rec.ticker,
        "sender": rec.sender,
        "action": rec.action,
        "strength": rec.strength,
        "rec_date": rec_date,
        "base_close": base_close,
    }

    for w in WINDOWS:
        if w > len(future_dates):
            break
        target_date = future_dates[w - 1]
        if target_date not in price_map:
            continue

        ret = (price_map[target_date] - base_close) / base_close
        win = (ret > 0) if bullish else (ret < 0)

        bench_ret = None
        excess = None
        if bench_base and target_date in bench_map:
            bench_ret = (bench_map[target_date] - bench_base) / bench_base
            excess = ret - bench_ret

        results[f"ret_t{w}"] = round(ret, 6)
        results[f"win_t{w}"] = win
        results[f"bench_ret_t{w}"] = round(bench_ret, 6) if bench_ret is not None else None
        results[f"excess_t{w}"] = round(excess, 6) if excess is not None else None

    return results


def run_backtest(date_str: str, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)
    recs = _load_recommendations(cfg.storage.data_dir, dt)

    if not recs:
        click.echo(f"{dt} 无推荐数据")
        return

    if not json_output:
        click.echo(f"回测 {dt}: {len(recs)} 条推荐", err=True)

    # -- 阶段 1: 名称→代码映射 --
    if not json_output:
        click.echo(f"\n[1/3] 名称→代码映射...", err=True)

    resolved_items: list[tuple[Recommendation, str]] = []
    skipped_tickers: list[str] = []

    for i, rec in enumerate(recs):
        ts_code = _resolve_ticker(rec.ticker)
        if not ts_code:
            if rec.ticker not in skipped_tickers:
                skipped_tickers.append(rec.ticker)
            continue
        rec_date = rec.message_time.strftime("%Y%m%d") if rec.message_time else dt.strftime("%Y%m%d")
        resolved_items.append((rec, ts_code))

    if not json_output:
        n_tickers = len(set(ts for _, ts in resolved_items))
        click.echo(f"  匹配: {len(resolved_items)} 条 ({n_tickers} 个标的), 跳过: {len(skipped_tickers)} 个", err=True)
        if skipped_tickers:
            click.echo(f"  未匹配: {', '.join(skipped_tickers[:15])}", err=True)

    # -- 阶段 2: 拉取行情数据 --
    if not json_output:
        click.echo(f"\n[2/3] 拉取行情数据 (本地有缓存则跳过)...", err=True)

    bt_results: list[dict] = []
    total = len(resolved_items)

    for i, (rec, ts_code) in enumerate(resolved_items):
        rec_date = rec.message_time.strftime("%Y%m%d") if rec.message_time else dt.strftime("%Y%m%d")
        result = _backtest_one(rec, ts_code, rec_date)
        if result:
            bt_results.append(result)

        if not json_output:
            done = i + 1
            pct = done * 100 // total
            bar = "█" * (pct // 4) + "░" * (25 - pct // 4)
            sys.stderr.write(f"\r  {bar} {pct:>3}% ({done}/{total})")
            sys.stderr.flush()

    if not json_output:
        sys.stderr.write("\n")
        sys.stderr.flush()

    # -- 阶段 3: 聚合统计 --
    if not json_output:
        click.echo(f"\n[3/3] 聚合推荐人统计...", err=True)

    out_dir = Path(cfg.storage.data_dir).expanduser() / dt.isoformat() / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(bt_results, ensure_ascii=False, indent=2), encoding="utf-8")

    sender_stats = _aggregate_by_sender(bt_results)

    stats_path = out_dir / "sender_stats.json"
    stats_path.write_text(json.dumps(sender_stats, ensure_ascii=False, indent=2), encoding="utf-8")

    if json_output:
        click.echo(json.dumps({"results": len(bt_results), "sender_stats": sender_stats}, ensure_ascii=False))
    else:
        click.echo(f"\n回测完成: {len(bt_results)} 条有效结果")
        click.echo(f"结果保存: {out_path}")

        header = f"{'推荐人':<16} {'次数':>4} "
        for w in WINDOWS:
            header += f" {'T+'+str(w)+' 胜率':>9}"
        header += f" {'T+5 均收益':>10} {'T+5 超额':>9}"
        click.echo(f"\n{header}")
        click.echo("-" * len(header.encode("gbk", errors="replace")))

        for s in sender_stats:
            line = f"{s['sender']:<16} {s['count']:>4} "
            for w in WINDOWS:
                wr = s.get(f"win_rate_t{w}")
                line += f" {wr*100:>8.1f}%" if wr is not None else f" {'--':>9}"
            avg = s.get("avg_ret_t5")
            exc = s.get("avg_excess_t5")
            line += f" {avg*100:>9.2f}%" if avg is not None else f" {'--':>10}"
            line += f" {exc*100:>8.2f}%" if exc is not None else f" {'--':>9}"
            click.echo(line)


def run_backtest_summary(
    json_output: bool,
    top: int | None = None,
    min_count: int = 1,
    window_days: int | None = 30,
) -> None:
    """跨天汇总：默认扫描近期回测结果，计算推荐人滚动胜率."""
    cfg = load()
    data_root = Path(cfg.storage.data_dir).expanduser()
    end_date = date.today()
    start_date = (
        end_date - timedelta(days=window_days)
        if window_days is not None
        else None
    )

    all_results: list[dict] = []
    dates_found: list[str] = []

    if not data_root.exists():
        click.echo("数据目录不存在")
        return

    for date_dir in sorted(data_root.iterdir()):
        if not date_dir.is_dir():
            continue
        results_file = date_dir / "backtest" / "results.json"
        if not results_file.exists():
            continue
        try:
            result_date = date.fromisoformat(date_dir.name)
        except ValueError:
            continue
        if start_date is not None and not (start_date <= result_date <= end_date):
            continue
        items = json.loads(results_file.read_text(encoding="utf-8"))
        if items:
            all_results.extend(items)
            dates_found.append(date_dir.name)

    if not all_results:
        if start_date is None:
            click.echo(
                "未找到任何回测结果，请先运行: sn analyze backtest --date <日期>"
            )
        else:
            date_range = f"{start_date.isoformat()} 至 {end_date.isoformat()}"
            click.echo(
                f"近 {window_days} 天未找到任何回测结果 ({date_range})，"
                "请先运行: sn analyze backtest --date <日期>"
            )
        return

    if not json_output:
        scope = "全部已有" if start_date is None else f"近 {window_days} 天"
        click.echo(
            f"汇总{scope}回测数据 ({len(dates_found)} 天): {', '.join(dates_found)}",
            err=True,
        )
        click.echo(f"共 {len(all_results)} 条推荐记录", err=True)

    sender_stats = _aggregate_by_sender(all_results)

    out_dir = data_root / "backtest_summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = out_dir / "sender_stats.json"
    stats_path.write_text(
        json.dumps(sender_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    meta = {
        "window_days": window_days,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if start_date else None,
        "dates": dates_found,
        "total_records": len(all_results),
        "senders": len(sender_stats),
    }
    meta_path = out_dir / "meta.json"
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if min_count > 1:
        sender_stats = [s for s in sender_stats if s["count"] >= min_count]

    display_stats = sender_stats[:top] if top else sender_stats

    if json_output:
        click.echo(
            json.dumps(
                {"meta": meta, "sender_stats": display_stats},
                ensure_ascii=False,
            )
        )
    else:
        if start_date is None:
            title = f"\n历史累计推荐人胜率排行 ({len(dates_found)} 天)"
        else:
            date_range = f"{start_date.isoformat()} 至 {end_date.isoformat()}"
            title = (
                f"\n近 {window_days} 天推荐人胜率排行 "
                f"({date_range}, {len(dates_found)} 天有结果)"
            )
        if top:
            title += f" — Top {top}"
        click.echo(title)

        header = f"{'推荐人':<16} {'次数':>4} "
        for w in WINDOWS:
            header += f" {'T+'+str(w)+' 胜率':>9}"
        header += f" {'T+5 均收益':>10} {'T+5 超额':>9}"
        click.echo(f"\n{header}")
        click.echo("-" * len(header.encode("gbk", errors="replace")))

        for s in display_stats:
            line = f"{s['sender']:<16} {s['count']:>4} "
            for w in WINDOWS:
                wr = s.get(f"win_rate_t{w}")
                line += f" {wr*100:>8.1f}%" if wr is not None else f" {'--':>9}"
            avg = s.get("avg_ret_t5")
            exc = s.get("avg_excess_t5")
            line += f" {avg*100:>9.2f}%" if avg is not None else f" {'--':>10}"
            line += f" {exc*100:>8.2f}%" if exc is not None else f" {'--':>9}"
            click.echo(line)

        click.echo(f"\n结果保存: {stats_path}")


def _aggregate_by_sender(results: list[dict]) -> list[dict]:
    by_sender: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_sender[r["sender"]].append(r)

    stats: list[dict] = []
    for sender, items in by_sender.items():
        s: dict[str, object] = {"sender": sender, "count": len(items)}
        for w in WINDOWS:
            wins = [r[f"win_t{w}"] for r in items if f"win_t{w}" in r]
            rets = [r[f"ret_t{w}"] for r in items if f"ret_t{w}" in r]
            excess = [r[f"excess_t{w}"] for r in items if r.get(f"excess_t{w}") is not None]
            if wins:
                s[f"win_rate_t{w}"] = round(sum(wins) / len(wins), 4)
                s[f"avg_ret_t{w}"] = round(sum(rets) / len(rets), 6)
            if excess:
                s[f"avg_excess_t{w}"] = round(sum(excess) / len(excess), 6)
        stats.append(s)

    stats.sort(key=lambda x: (x.get("win_rate_t5") or 0, x.get("count", 0)), reverse=True)
    return stats
