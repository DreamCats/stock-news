"""阿里云发布能力。

这里封装把本地生成文件发布到阿里云 Caddy 静态目录的最小能力。
"""

from stock_news.core.aly.publisher import AlyPublisher, AlyPublishResult, publish_file

__all__ = ["AlyPublishResult", "AlyPublisher", "publish_file"]
