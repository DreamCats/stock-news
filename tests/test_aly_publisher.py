"""阿里云发布器测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from stock_news.core.aly import publish_file
from stock_news.models import AlyConfig


def test_publish_file_uploads_to_remote_dir(monkeypatch: Any, tmp_path: Path) -> None:
    local = tmp_path / "top32.html"
    local.write_text("<html></html>", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("stock_news.core.aly.publisher.subprocess.run", fake_run)

    result = publish_file(
        AlyConfig(
            host="39.106.190.32",
            user="root",
            password="secret",
            remote_dir="/usr/share/caddy/stock-news",
            url_prefix="https://example.com/stock-news",
        ),
        local,
        "2026-06-25/top32.html",
    )

    assert result.remote_path == "/usr/share/caddy/stock-news/2026-06-25/top32.html"
    assert result.url == "https://example.com/stock-news/2026-06-25/top32.html"
    assert commands[0][:3] == ["sshpass", "-p", "secret"]
    assert commands[0][3:6] == ["ssh", "-p", "22"]
    assert commands[0][-3:] == [
        "mkdir",
        "-p",
        "/usr/share/caddy/stock-news/2026-06-25",
    ]
    assert commands[1][:3] == ["sshpass", "-p", "secret"]
    assert commands[1][3:6] == ["scp", "-P", "22"]
    assert commands[1][-1] == (
        "root@39.106.190.32:/usr/share/caddy/stock-news/2026-06-25/top32.html"
    )
