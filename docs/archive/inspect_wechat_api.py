#!/usr/bin/env python3
"""Inspect WeChat recommendation API shape and sample records."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any


BASE_URL = "https://example.com/api"
DEFAULT_NAMES = ("个人消息", "个人群")
DEFAULT_STARTTIME = "20260521220000"
DEFAULT_ENDTIME = "20990101000000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch WeChat APIs and summarize response schema."
    )
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--name", action="append", dest="names", help="API name param")
    parser.add_argument("--starttime", default=DEFAULT_STARTTIME)
    parser.add_argument("--endtime", default=DEFAULT_ENDTIME)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--content-width", type=int, default=160)
    return parser.parse_args()


def build_url(base_url: str, name: str, starttime: str, endtime: str) -> str:
    query = urllib.parse.urlencode(
        {"name": name, "starttime": starttime, "endtime": endtime}
    )
    return f"{base_url}?{query}"


def fetch_json(url: str, timeout: float) -> tuple[dict[str, Any], Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        metadata = {
            "status": response.status,
            "content_type": response.headers.get("Content-Type", ""),
        }
        body = response.read()

    metadata["bytes"] = len(body)
    text = body.decode("utf-8-sig")
    return metadata, json.loads(text)


def stringify(value: Any, width: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def print_summary(name: str, url: str, metadata: dict[str, Any], payload: Any, args: argparse.Namespace) -> None:
    print(f"\n## {name}")
    print(f"url: {url}")
    print(f"status: {metadata.get('status')}")
    print(f"content_type: {metadata.get('content_type') or '-'}")
    print(f"bytes: {metadata.get('bytes')}")
    print(f"top_level_type: {type(payload).__name__}")

    if not isinstance(payload, list):
        print("note: top-level payload is not a list; raw shape needs separate handling.")
        return

    print(f"record_count: {len(payload)}")
    records = [record for record in payload if isinstance(record, dict)]
    print(f"object_record_count: {len(records)}")
    if not records:
        return

    field_counter: Counter[str] = Counter()
    sender_counter: Counter[str] = Counter()
    times: list[str] = []
    for record in records:
        field_counter.update(record.keys())
        sender = record.get("发送人")
        if sender:
            sender_counter[str(sender)] += 1
        record_time = record.get("时间")
        if record_time:
            times.append(str(record_time))

    print("fields:")
    for field, count in field_counter.most_common():
        missing = len(records) - count
        print(f"  - {field}: present={count}, missing={missing}")

    if times:
        print(f"time_range: {min(times)} -> {max(times)}")

    if sender_counter:
        print("top_senders:")
        for sender, count in sender_counter.most_common(10):
            print(f"  - {stringify(sender, 40)}: {count}")

    print("samples:")
    for index, record in enumerate(records[: args.sample_size], start=1):
        print(f"  sample_{index}:")
        for key in ("时间", "发送人", "内容"):
            print(f"    {key}: {stringify(record.get(key), args.content_width)}")


def main() -> int:
    args = parse_args()
    names = args.names or list(DEFAULT_NAMES)

    for name in names:
        url = build_url(args.base_url, name, args.starttime, args.endtime)
        try:
            metadata, payload = fetch_json(url, args.timeout)
        except urllib.error.URLError as exc:
            print(f"\n## {name}", file=sys.stderr)
            print(f"fetch_failed: {exc}", file=sys.stderr)
            continue
        except json.JSONDecodeError as exc:
            print(f"\n## {name}", file=sys.stderr)
            print(f"json_decode_failed: {exc}", file=sys.stderr)
            continue

        print_summary(name, url, metadata, payload, args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
