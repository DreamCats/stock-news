"""python -m stock_news 入口。

后台调度进程用这个入口启动，避免依赖当前 shell 里的 sn 可执行文件路径。
"""

from __future__ import annotations

from stock_news.cli import cli_main

cli_main()
