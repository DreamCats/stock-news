"""通用 SQLite 基础能力。

这里只放连接、事务这类跨领域能力；具体表结构留在各领域 store。
"""

from stock_news.core.db.sqlite import sqlite_connection

__all__ = ["sqlite_connection"]
