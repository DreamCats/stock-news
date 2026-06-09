"""每日晚报路径约定."""

from __future__ import annotations

from datetime import date
from pathlib import Path


def nightly_paths(data_dir: str, dt: date) -> tuple[Path, Path]:
    out_dir = Path(data_dir).expanduser() / dt.isoformat() / "nightly"
    return out_dir / "nightly.json", out_dir / "nightly.html"
