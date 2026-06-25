"""阿里云静态文件发布器。

这里使用 ssh/scp 或 sshpass 把本地 HTML 发布到配置里的远程 Caddy 目录。
"""

from __future__ import annotations

import posixpath
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from stock_news.models import AlyConfig


class AlyPublishError(RuntimeError):
    """阿里云发布失败。"""


@dataclass(frozen=True)
class AlyPublishResult:
    """一次阿里云文件发布结果。"""

    local_path: Path
    remote_path: str
    url: str


class AlyPublisher:
    """把本地文件发布到 Aly 配置对应的远程目录。"""

    def __init__(self, config: AlyConfig) -> None:
        self.config = config

    def publish(self, local_path: Path, remote_relative_path: str) -> AlyPublishResult:
        """发布单个文件并返回访问 URL。"""

        return publish_file(self.config, local_path, remote_relative_path)


def publish_file(
    config: AlyConfig,
    local_path: Path,
    remote_relative_path: str,
) -> AlyPublishResult:
    """把本地文件复制到阿里云远程目录。"""

    local = local_path.expanduser()
    if not local.exists():
        raise AlyPublishError(f"本地文件不存在: {local}")
    _validate_config(config)
    relative = _clean_relative_path(remote_relative_path)
    remote_path = posixpath.join(config.remote_dir.rstrip("/"), relative)
    remote_parent = posixpath.dirname(remote_path)
    target = f"{config.user}@{config.host}"

    _run(
        _auth_prefix(config)
        + [
            "ssh",
            "-p",
            str(config.port),
            "-o",
            "StrictHostKeyChecking=no",
            target,
            "mkdir",
            "-p",
            remote_parent,
        ]
    )
    _run(
        _auth_prefix(config)
        + [
            "scp",
            "-P",
            str(config.port),
            "-o",
            "StrictHostKeyChecking=no",
            str(local),
            f"{target}:{remote_path}",
        ]
    )
    return AlyPublishResult(
        local_path=local,
        remote_path=remote_path,
        url=_public_url(config.url_prefix, relative),
    )


def _validate_config(config: AlyConfig) -> None:
    if not config.host:
        raise AlyPublishError("Aly host 未配置")
    if not config.user:
        raise AlyPublishError("Aly user 未配置")
    if not config.remote_dir:
        raise AlyPublishError("Aly remote_dir 未配置")
    if not config.url_prefix:
        raise AlyPublishError("Aly url_prefix 未配置")
    if config.password and not config.sshpass_path:
        raise AlyPublishError("Aly password 已配置，但 sshpass_path 为空")


def _clean_relative_path(value: str) -> str:
    cleaned = value.strip().lstrip("/")
    parts = [part for part in cleaned.split("/") if part]
    if not parts or any(part == ".." for part in parts):
        raise AlyPublishError(f"非法远程相对路径: {value}")
    return "/".join(parts)


def _auth_prefix(config: AlyConfig) -> list[str]:
    if not config.password:
        return []
    return [config.sshpass_path, "-p", config.password]


def _public_url(prefix: str, relative: str) -> str:
    return f"{prefix.rstrip('/')}/{quote(relative, safe='/')}"


def _run(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise AlyPublishError(f"发布命令不存在: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AlyPublishError(f"发布命令失败: {detail}") from exc
