"""每日晚报静态发布."""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path
from shlex import quote

from stock_news.models import NightlyPublishConfig
from stock_news.signals.nightly_report.models import PublishOutput


def publish_nightly_html(
    local_html: Path,
    dt: date,
    config: NightlyPublishConfig,
) -> PublishOutput:
    """发布晚报 HTML 到静态服务器."""
    if not local_html.exists():
        raise ValueError(f"晚报 HTML 不存在: {local_html}")
    if not config.host or not config.user:
        raise ValueError("请先配置 publish.nightly.host 和 publish.nightly.user")
    if not config.password:
        raise ValueError("请先配置 publish.nightly.password")
    if not config.url_prefix:
        raise ValueError("请先配置 publish.nightly.url_prefix")

    remote_dir = config.remote_dir.rstrip("/")
    remote_month_dir = f"{remote_dir}/{dt:%Y/%m}"
    remote_name = f"nightly-{dt.isoformat()}.html"
    remote_path = f"{remote_month_dir}/{remote_name}"
    ssh_target = f"{config.user}@{config.host}"
    env = os.environ.copy()
    env["SSHPASS"] = config.password
    ssh_opts = [
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]

    _run_publish_cmd(
        [
            config.sshpass_path,
            "-e",
            "ssh",
            *ssh_opts,
            "-p",
            str(config.port),
            ssh_target,
            f"mkdir -p {quote(remote_month_dir)}",
        ],
        env,
    )
    _run_publish_cmd(
        [
            config.sshpass_path,
            "-e",
            "scp",
            *ssh_opts,
            "-P",
            str(config.port),
            str(local_html),
            f"{ssh_target}:{remote_path}",
        ],
        env,
    )
    url = f"{config.url_prefix.rstrip('/')}/{dt:%Y/%m}/{remote_name}"
    return PublishOutput(local_path=local_html, remote_path=remote_path, url=url)


def _run_publish_cmd(args: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode == 0:
        return
    stderr = result.stderr.strip() or result.stdout.strip()
    raise RuntimeError(stderr or f"命令失败: {args[0]}")
