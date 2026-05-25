"""统一异常体系."""


class StockNewsError(Exception):
    """基础异常."""


class ConfigError(StockNewsError):
    """配置相关错误."""


class APIError(StockNewsError):
    """API 请求错误."""


class StorageError(StockNewsError):
    """存储相关错误."""
