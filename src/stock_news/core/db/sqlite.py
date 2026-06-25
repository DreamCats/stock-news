"""SQLite 连接工具。

这里提供统一的连接上下文，负责建目录、设置 row_factory 和提交事务。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def sqlite_connection(path: str | Path) -> Iterator[sqlite3.Connection]:
    """打开 SQLite 连接，并在退出时提交和关闭。"""

    db_path = Path(path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
