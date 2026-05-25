"""历史窗口补齐编排."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta

import click

from stock_news.commands.analyze._common import parse_date
from stock_news.commands.analyze.classify import classify
from stock_news.commands.analyze.extract import extract
from stock_news.commands.analyze.opinion import opinion
from stock_news.commands.fetch import run_fetch

StepFn = Callable[[], None]


def _date_range(end_date: str, days: int) -> list[str]:
    end = parse_date(end_date)
    start = end - timedelta(days=days - 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def _run_step(step: StepFn, capture_output: bool) -> str:
    if not capture_output:
        step()
        return ""

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        step()
    return (out.getvalue() + err.getvalue()).strip()


def run_backfill(
    days: int,
    end_date: str,
    time_range: str,
    source: str,
    provider_name: str | None,
    slice_hours: int,
    workers: int,
    dry_run: bool,
    json_output: bool,
) -> None:
    """按天顺序补齐 fetch → classify → extract → opinion."""
    dates = _date_range(end_date, days)
    phases = ["fetch", "classify", "extract", "opinion"]

    if dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "dates": dates,
            "phases": phases,
            "time_range": time_range,
            "source": source,
        }
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(
                f"将补齐 {len(dates)} 天: {dates[0]} 至 {dates[-1]} "
                f"({', '.join(phases)})"
            )
        return

    results: list[dict[str, object]] = []

    for date_str in dates:
        if not json_output:
            click.echo(f"\n=== 补齐 {date_str} ===", err=True)

        date_result: dict[str, object] = {
            "date": date_str,
            "ok": True,
            "phases": [],
        }
        phase_results: list[dict[str, object]] = []

        current_date = date_str

        def fetch_step() -> None:
            run_fetch(
                source,
                None,
                None,
                None,
                current_date,
                time_range,
                False,
                slice_hours,
                workers,
                False,
            )

        def classify_step() -> None:
            classify(current_date, False, provider_name, False)

        def extract_step() -> None:
            extract(current_date, provider_name, False)

        def opinion_step() -> None:
            opinion(current_date, provider_name, False)

        steps: list[tuple[str, StepFn]] = [
            ("fetch", fetch_step),
            ("classify", classify_step),
            ("extract", extract_step),
            ("opinion", opinion_step),
        ]

        for phase_name, step in steps:
            if not json_output:
                click.echo(f"[{date_str}] {phase_name}...", err=True)
            try:
                output = _run_step(step, capture_output=json_output)
                phase_results.append(
                    {
                        "phase": phase_name,
                        "ok": True,
                        "output": output[-1000:] if output else "",
                    }
                )
            except Exception as exc:
                date_result["ok"] = False
                phase_results.append(
                    {
                        "phase": phase_name,
                        "ok": False,
                        "error": str(exc),
                    }
                )
                if not json_output:
                    click.secho(f"  {phase_name} 失败: {exc}", fg="red", err=True)

        date_result["phases"] = phase_results
        results.append(date_result)

    ok = all(bool(item["ok"]) for item in results)
    if json_output:
        click.echo(
            json.dumps(
                {
                    "ok": ok,
                    "data": {
                        "dates": dates,
                        "days": len(dates),
                        "time_range": time_range,
                        "source": source,
                        "results": results,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        failed = [str(item["date"]) for item in results if not item["ok"]]
        if failed:
            click.echo(f"\n补齐完成，失败 {len(failed)} 天: {', '.join(failed)}")
        else:
            click.echo(f"\n补齐完成: {len(dates)} 天")
