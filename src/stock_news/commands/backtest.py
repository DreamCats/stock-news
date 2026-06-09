"""推荐人胜率回测命令适配层."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import click

from stock_news.backtest import engine, refresh, storage, summary
from stock_news.backtest.constants import CHECKPOINT_EVERY_REFRESHED, WINDOWS
from stock_news.backtest.utils import parse_date as _parse_date
from stock_news.common.config import load

# 兼容旧测试/临时调用；真实业务调用走 backtest 领域模块。
_aggregate_by_sender = summary.aggregate_by_sender
_backtest_one = engine.backtest_one
_load_backtest_results = storage.load_backtest_results
_load_recommendations = storage.load_recommendations
_mature_windows = engine.mature_windows
_refresh_one_day = refresh.refresh_one_day
_resolve_ticker = engine.resolve_ticker
_save_backtest_results = storage.save_backtest_results


def run_backtest(date_str: str, json_output: bool) -> None:
    cfg = load()
    dt = _parse_date(date_str)
    as_of = date.today()
    progress = _progress_printer(enabled=not json_output)
    if progress:
        progress(f"刷新单日回测: {dt.isoformat()}，截至 {as_of.isoformat()}")

    stats = refresh.refresh_one_day(
        cfg.storage.data_dir,
        dt,
        as_of,
        ticker_cache={},
        mature_cache={},
        progress=progress,
        label="[1/1]",
        checkpoint_every=CHECKPOINT_EVERY_REFRESHED,
    )
    bt_results = storage.load_backtest_results(cfg.storage.data_dir, dt)
    sender_stats = summary.aggregate_by_sender(bt_results)

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
        return

    out_path = (
        Path(cfg.storage.data_dir).expanduser()
        / dt.isoformat()
        / "backtest"
        / "results.json"
    )
    click.echo(f"\n回测刷新完成: {len(bt_results)} 条有效结果")
    click.echo(f"结果保存: {out_path}")
    _echo_sender_table(sender_stats)


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
    progress = _progress_printer(enabled=not json_output)

    if progress:
        progress(f"刷新回测: {start_date.isoformat()} 至 {as_of.isoformat()}")

    for offset in range(window_days):
        dt = start_date + timedelta(days=offset)
        recs = storage.load_recommendations(cfg.storage.data_dir, dt)
        if not recs:
            if progress:
                progress(
                    f"[{offset + 1}/{window_days}] {dt.isoformat()} 无推荐数据，跳过"
                )
            continue

        scanned_dates += 1
        day_stats = refresh.refresh_one_day(
            cfg.storage.data_dir,
            dt,
            as_of,
            ticker_cache,
            mature_cache,
            progress=progress,
            label=f"[{offset + 1}/{window_days}]",
            checkpoint_every=CHECKPOINT_EVERY_REFRESHED,
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
        "changed_dates": [dt.isoformat() for dt in sorted(changed_dates)],
    }

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

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
        _echo_no_summary_results(start_date, end_date, window_days)
        return

    if not json_output:
        scope = "全部已有" if start_date is None else f"近 {window_days} 天"
        click.echo(
            f"汇总{scope}回测数据 ({len(dates_found)} 天): {', '.join(dates_found)}",
            err=True,
        )
        click.echo(f"共 {len(all_results)} 条推荐记录", err=True)

    sender_stats = summary.aggregate_by_sender(all_results)
    stats_path = _save_summary_outputs(
        data_root,
        sender_stats,
        window_days,
        start_date,
        end_date,
        dates_found,
        len(all_results),
    )

    meta = {
        "window_days": window_days,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if start_date else None,
        "dates": dates_found,
        "total_records": len(all_results),
        "senders": len(sender_stats),
    }
    if min_count > 1:
        sender_stats = [item for item in sender_stats if item["count"] >= min_count]
    display_stats = sender_stats[:top] if top else sender_stats

    if json_output:
        click.echo(
            json.dumps(
                {"meta": meta, "sender_stats": display_stats},
                ensure_ascii=False,
            )
        )
        return

    _echo_summary_table(
        display_stats,
        dates_found,
        start_date,
        end_date,
        window_days,
        top,
    )
    click.echo(f"\n结果保存: {stats_path}")


def _progress_printer(enabled: bool) -> refresh.ProgressCallback | None:
    if not enabled:
        return None
    return lambda message: click.echo(message, err=True)


def _echo_sender_table(sender_stats: list[dict[str, Any]]) -> None:
    header = f"{'推荐人':<16} {'次数':>4} "
    for window in WINDOWS:
        header += f" {'T+' + str(window) + ' 胜率':>9}"
    header += f" {'T+5 均收益':>10} {'T+5 超额':>9}"
    click.echo(f"\n{header}")
    click.echo("-" * len(header.encode("gbk", errors="replace")))

    for item in sender_stats:
        line = f"{item['sender']:<16} {item['count']:>4} "
        for window in WINDOWS:
            win_rate = item.get(f"win_rate_t{window}")
            line += (
                f" {win_rate * 100:>8.1f}%" if win_rate is not None else f" {'--':>9}"
            )
        avg = item.get("avg_ret_t5")
        excess = item.get("avg_excess_t5")
        line += f" {avg * 100:>9.2f}%" if avg is not None else f" {'--':>10}"
        line += f" {excess * 100:>8.2f}%" if excess is not None else f" {'--':>9}"
        click.echo(line)


def _echo_no_summary_results(
    start_date: date | None,
    end_date: date,
    window_days: int | None,
) -> None:
    if start_date is None:
        click.echo("未找到任何回测结果，请先运行: sn analyze backtest --date <日期>")
        return
    date_range = f"{start_date.isoformat()} 至 {end_date.isoformat()}"
    click.echo(
        f"近 {window_days} 天未找到任何回测结果 ({date_range})，"
        "请先运行: sn analyze backtest --date <日期>"
    )


def _save_summary_outputs(
    data_root: Path,
    sender_stats: list[dict[str, Any]],
    window_days: int | None,
    start_date: date | None,
    end_date: date,
    dates_found: list[str],
    total_records: int,
) -> Path:
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
        "total_records": total_records,
        "senders": len(sender_stats),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stats_path


def _echo_summary_table(
    display_stats: list[dict[str, Any]],
    dates_found: list[str],
    start_date: date | None,
    end_date: date,
    window_days: int | None,
    top: int | None,
) -> None:
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
    _echo_sender_table(display_stats)
