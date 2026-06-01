"""推荐人胜率回测."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
    path = (
        Path(data_dir).expanduser()
        / dt.isoformat()
        / "extracted"
        / "recommendations.json"
    )
    if not path.exists():
        return []
    return [
        Recommendation.model_validate(i)
        for i in json.loads(path.read_text(encoding="utf-8"))
    ]


def _resolve_ticker(name: str) -> str | None:
    """股票名称 → ts_code，匹配不上返回 None."""
    from stock_news.common.market.db import get_ts_code

    return get_ts_code(name)


def _is_bullish(action: str) -> bool:
    return action in ("买入", "加仓", "关注")


def _mature_windows(rec_dt: date, as_of: date) -> list[int]:
    """返回 as_of 当天已经成熟的 T+N 窗口."""
    from stock_news.common.market.db import get_next_n_trade_dates

    future_dates = get_next_n_trade_dates(rec_dt, max(WINDOWS))
    return [
        w
        for w in WINDOWS
        if w <= len(future_dates) and future_dates[w - 1] <= as_of.strftime("%Y%m%d")
    ]


def _backtest_one(
    rec: Recommendation,
    ts_code: str,
    rec_date: str,
    as_of: date | None = None,
) -> dict[str, Any] | None:
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

    if as_of is not None:
        mature = _mature_windows(rec_dt, as_of)
        if not mature:
            return None
    else:
        mature = WINDOWS

    max_window = max(mature)
    end_date = future_dates[max_window - 1]
    future_rows = fetch_daily(ts_code, future_dates[0], end_date)
    price_map = {r["trade_date"]: r["close"] for r in future_rows}

    bench_base_rows = fetch_index_daily(BENCHMARK, rec_date, rec_date)
    if not bench_base_rows:
        start_minus = (rec_dt - timedelta(days=5)).strftime("%Y%m%d")
        bench_base_rows = fetch_index_daily(BENCHMARK, start_minus, rec_date)
    bench_base = bench_base_rows[-1]["close"] if bench_base_rows else None

    bench_rows = (
        fetch_index_daily(BENCHMARK, future_dates[0], end_date) if bench_base else []
    )
    bench_map = {r["trade_date"]: r["close"] for r in bench_rows}

    bullish = _is_bullish(rec.action)
    results: dict[str, object] = {
        "message_id": rec.message_id,
        "ts_code": ts_code,
        "ticker": rec.ticker,
        "sender": rec.sender,
        "action": rec.action,
        "strength": rec.strength,
        "rec_date": rec_date,
        "base_close": base_close,
    }

    for w in mature:
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
        results[f"bench_ret_t{w}"] = (
            round(bench_ret, 6) if bench_ret is not None else None
        )
        results[f"excess_t{w}"] = round(excess, 6) if excess is not None else None

    return results


def run_backtest(date_str: str, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)
    as_of = date.today()
    if not json_output:
        click.echo(
            f"刷新单日回测: {dt.isoformat()}，截至 {as_of.isoformat()}",
            err=True,
        )

    stats = _refresh_one_day(
        cfg.storage.data_dir,
        dt,
        as_of,
        ticker_cache={},
        mature_cache={},
        json_output=json_output,
        label="[1/1]",
    )
    bt_results = _load_backtest_results(cfg.storage.data_dir, dt)
    sender_stats = _aggregate_by_sender(bt_results)

    if json_output:
        click.echo(
            json.dumps(
                {
                    "date": dt.isoformat(),
                    "as_of": as_of.isoformat(),
                    **stats,
                    "results": len(bt_results),
                    "sender_stats": sender_stats,
                },
                ensure_ascii=False,
            )
        )
    else:
        out_path = (
            Path(cfg.storage.data_dir).expanduser()
            / dt.isoformat()
            / "backtest"
            / "results.json"
        )
        click.echo(f"\n回测刷新完成: {len(bt_results)} 条有效结果")
        click.echo(f"结果保存: {out_path}")

        header = f"{'推荐人':<16} {'次数':>4} "
        for w in WINDOWS:
            header += f" {'T+' + str(w) + ' 胜率':>9}"
        header += f" {'T+5 均收益':>10} {'T+5 超额':>9}"
        click.echo(f"\n{header}")
        click.echo("-" * len(header.encode("gbk", errors="replace")))

        for s in sender_stats:
            line = f"{s['sender']:<16} {s['count']:>4} "
            for w in WINDOWS:
                wr = s.get(f"win_rate_t{w}")
                line += f" {wr * 100:>8.1f}%" if wr is not None else f" {'--':>9}"
            avg = s.get("avg_ret_t5")
            exc = s.get("avg_excess_t5")
            line += f" {avg * 100:>9.2f}%" if avg is not None else f" {'--':>10}"
            line += f" {exc * 100:>8.2f}%" if exc is not None else f" {'--':>9}"
            click.echo(line)


def _result_key_from_rec(rec: Recommendation) -> tuple[str, ...]:
    return ("rec", rec.message_id, rec.ticker, rec.action)


def _legacy_result_key_from_rec(rec: Recommendation) -> tuple[str, ...]:
    rec_date = rec.message_time.strftime("%Y%m%d") if rec.message_time else ""
    return ("legacy", rec.sender, rec.ticker, rec.action, rec_date)


def _result_key_from_result(item: dict[str, Any]) -> tuple[str, ...]:
    message_id = item.get("message_id")
    ticker = item.get("ticker")
    action = item.get("action")
    if message_id and ticker and action:
        return ("rec", str(message_id), str(ticker), str(action))
    if message_id:
        return ("message_id", str(message_id))
    return (
        "legacy",
        str(item.get("sender", "")),
        str(item.get("ticker", "")),
        str(item.get("action", "")),
        str(item.get("rec_date", "")),
    )


def _load_backtest_results(data_dir: str, dt: date) -> list[dict[str, Any]]:
    path = Path(data_dir).expanduser() / dt.isoformat() / "backtest" / "results.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_backtest_results(
    data_dir: str,
    dt: date,
    results: list[dict[str, Any]],
) -> None:
    out_dir = Path(data_dir).expanduser() / dt.isoformat() / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sender_stats = _aggregate_by_sender(results)
    stats_path = out_dir / "sender_stats.json"
    stats_path.write_text(
        json.dumps(sender_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _result_with_rec_identity(
    result: dict[str, Any],
    rec: Recommendation,
    ts_code: str,
    rec_date: str,
) -> dict[str, Any]:
    return {
        **result,
        "message_id": rec.message_id,
        "ts_code": ts_code,
        "ticker": rec.ticker,
        "sender": rec.sender,
        "action": rec.action,
        "strength": rec.strength,
        "rec_date": rec_date,
    }


def _emit_refresh_progress(
    done: int,
    total: int,
    refreshed: int,
    skipped_complete: int,
    pending: int,
    unmatched: int,
    json_output: bool,
    last_progress_at: float,
) -> float:
    if json_output:
        return last_progress_at

    now = time.monotonic()
    if done < total and done % 500 != 0 and now - last_progress_at < 10:
        return last_progress_at

    click.echo(
        "  进度: "
        f"{done}/{total}，更新 {refreshed}，完整跳过 {skipped_complete}，"
        f"未成熟 {pending}，未匹配 {unmatched}",
        err=True,
    )
    return now


def _refresh_one_day(
    cfg_data_dir: str,
    dt: date,
    as_of: date,
    ticker_cache: dict[str, str | None],
    mature_cache: dict[date, list[int]],
    json_output: bool,
    label: str | None = None,
) -> dict[str, Any]:
    recs = _load_recommendations(cfg_data_dir, dt)
    stats: dict[str, Any] = {
        "date": dt.isoformat(),
        "recommendations": len(recs),
        "refreshed": 0,
        "skipped_complete": 0,
        "pending": 0,
        "unmatched": 0,
        "changed": False,
    }
    if not recs:
        if not json_output and label:
            click.echo(f"{label} {dt.isoformat()} 无推荐数据，跳过", err=True)
        return stats

    existing = _load_backtest_results(cfg_data_dir, dt)
    by_key = {_result_key_from_result(item): item for item in existing}
    backtest_cache: dict[tuple[str, str, str, str], dict[str, Any] | None] = {}
    last_progress_at = time.monotonic()

    if not json_output and label:
        click.echo(f"{label} {dt.isoformat()} 推荐 {len(recs)} 条", err=True)

    for i, rec in enumerate(recs, start=1):
        rec_dt = rec.message_time.date() if rec.message_time else dt
        mature = mature_cache.get(rec_dt)
        if mature is None:
            mature = _mature_windows(rec_dt, as_of)
            mature_cache[rec_dt] = mature
        if not mature:
            stats["pending"] += 1
            last_progress_at = _emit_refresh_progress(
                i,
                len(recs),
                stats["refreshed"],
                stats["skipped_complete"],
                stats["pending"],
                stats["unmatched"],
                json_output,
                last_progress_at,
            )
            continue

        key = _result_key_from_rec(rec)
        legacy_keys = [
            ("message_id", rec.message_id),
            _legacy_result_key_from_rec(rec),
        ]
        old = by_key.get(key)
        if old is None:
            old = next((by_key[k] for k in legacy_keys if k in by_key), None)
        missing = [w for w in mature if not old or f"ret_t{w}" not in old]
        if not missing:
            stats["skipped_complete"] += 1
            last_progress_at = _emit_refresh_progress(
                i,
                len(recs),
                stats["refreshed"],
                stats["skipped_complete"],
                stats["pending"],
                stats["unmatched"],
                json_output,
                last_progress_at,
            )
            continue

        if rec.ticker not in ticker_cache:
            ticker_cache[rec.ticker] = _resolve_ticker(rec.ticker)
        ts_code = ticker_cache[rec.ticker]
        if not ts_code:
            stats["unmatched"] += 1
            last_progress_at = _emit_refresh_progress(
                i,
                len(recs),
                stats["refreshed"],
                stats["skipped_complete"],
                stats["pending"],
                stats["unmatched"],
                json_output,
                last_progress_at,
            )
            continue

        rec_date = (
            rec.message_time.strftime("%Y%m%d")
            if rec.message_time
            else dt.strftime("%Y%m%d")
        )
        cache_key = (ts_code, rec_date, rec.action, as_of.isoformat())
        if cache_key not in backtest_cache:
            backtest_cache[cache_key] = _backtest_one(
                rec,
                ts_code,
                rec_date,
                as_of=as_of,
            )

        cached_result = backtest_cache[cache_key]
        if cached_result:
            result = _result_with_rec_identity(cached_result, rec, ts_code, rec_date)
            for legacy_key in legacy_keys:
                by_key.pop(legacy_key, None)
            by_key[key] = result
            stats["refreshed"] += 1
            stats["changed"] = True

        last_progress_at = _emit_refresh_progress(
            i,
            len(recs),
            stats["refreshed"],
            stats["skipped_complete"],
            stats["pending"],
            stats["unmatched"],
            json_output,
            last_progress_at,
        )

    if stats["changed"]:
        _save_backtest_results(
            cfg_data_dir,
            dt,
            sorted(
                by_key.values(),
                key=lambda item: (
                    str(item.get("message_id", "")),
                    str(item.get("ticker", "")),
                    str(item.get("action", "")),
                ),
            ),
        )

    if not json_output:
        click.echo(
            "  完成: "
            f"更新 {stats['refreshed']}，完整跳过 {stats['skipped_complete']}，"
            f"未成熟 {stats['pending']}，未匹配 {stats['unmatched']}",
            err=True,
        )
    return stats


def run_backtest_refresh(
    as_of_str: str,
    window_days: int,
    json_output: bool,
) -> None:
    """刷新过去 N 天推荐里已经成熟的 T+N 回测窗口."""
    cfg = load()
    as_of = _parse_date(as_of_str)
    start_date = as_of - timedelta(days=window_days - 1)
    scanned_dates = 0
    scanned_recs = 0
    refreshed = 0
    skipped_complete = 0
    pending = 0
    unmatched = 0
    changed_dates: set[date] = set()
    ticker_cache: dict[str, str | None] = {}
    mature_cache: dict[date, list[int]] = {}

    if not json_output:
        click.echo(
            f"刷新回测: {start_date.isoformat()} 至 {as_of.isoformat()}",
            err=True,
        )

    for offset in range(window_days):
        dt = start_date + timedelta(days=offset)
        recs = _load_recommendations(cfg.storage.data_dir, dt)
        if not recs:
            if not json_output:
                click.echo(
                    f"[{offset + 1}/{window_days}] {dt.isoformat()} 无推荐数据，跳过",
                    err=True,
                )
            continue

        scanned_dates += 1
        day_stats = _refresh_one_day(
            cfg.storage.data_dir,
            dt,
            as_of,
            ticker_cache,
            mature_cache,
            json_output,
            label=f"[{offset + 1}/{window_days}]",
        )
        scanned_recs += day_stats["recommendations"]
        refreshed += day_stats["refreshed"]
        skipped_complete += day_stats["skipped_complete"]
        pending += day_stats["pending"]
        unmatched += day_stats["unmatched"]
        if day_stats["changed"]:
            changed_dates.add(dt)

    payload = {
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "scanned_dates": scanned_dates,
        "scanned_recommendations": scanned_recs,
        "refreshed": refreshed,
        "skipped_complete": skipped_complete,
        "pending": pending,
        "unmatched": unmatched,
        "changed_dates": [d.isoformat() for d in sorted(changed_dates)],
    }

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        click.echo(
            "刷新完成: "
            f"扫描 {scanned_dates} 天 / {scanned_recs} 条，"
            f"更新 {refreshed} 条，完整跳过 {skipped_complete} 条，"
            f"未成熟 {pending} 条，未匹配 {unmatched} 条"
        )


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
        end_date - timedelta(days=window_days) if window_days is not None else None
    )

    all_results: list[dict[str, Any]] = []
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
            header += f" {'T+' + str(w) + ' 胜率':>9}"
        header += f" {'T+5 均收益':>10} {'T+5 超额':>9}"
        click.echo(f"\n{header}")
        click.echo("-" * len(header.encode("gbk", errors="replace")))

        for s in display_stats:
            line = f"{s['sender']:<16} {s['count']:>4} "
            for w in WINDOWS:
                wr = s.get(f"win_rate_t{w}")
                line += f" {wr * 100:>8.1f}%" if wr is not None else f" {'--':>9}"
            avg = s.get("avg_ret_t5")
            exc = s.get("avg_excess_t5")
            line += f" {avg * 100:>9.2f}%" if avg is not None else f" {'--':>10}"
            line += f" {exc * 100:>8.2f}%" if exc is not None else f" {'--':>9}"
            click.echo(line)

        click.echo(f"\n结果保存: {stats_path}")


def _aggregate_by_sender(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sender: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_sender[r["sender"]].append(r)

    stats: list[dict[str, Any]] = []
    for sender, items in by_sender.items():
        s: dict[str, object] = {"sender": sender, "count": len(items)}
        for w in WINDOWS:
            wins = [r[f"win_t{w}"] for r in items if f"win_t{w}" in r]
            rets = [r[f"ret_t{w}"] for r in items if f"ret_t{w}" in r]
            excess = [
                r[f"excess_t{w}"] for r in items if r.get(f"excess_t{w}") is not None
            ]
            if wins:
                s[f"win_rate_t{w}"] = round(sum(wins) / len(wins), 4)
                s[f"avg_ret_t{w}"] = round(sum(rets) / len(rets), 6)
            if excess:
                s[f"avg_excess_t{w}"] = round(sum(excess) / len(excess), 6)
        stats.append(s)

    stats.sort(
        key=lambda x: (x.get("win_rate_t5") or 0, x.get("count", 0)),
        reverse=True,
    )
    return stats
