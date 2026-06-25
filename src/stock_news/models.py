"""配置数据模型。

当前项目只保留配置能力；这里集中声明模型供应商、微信数据源、
Tushare、定时任务和渠道配置的强类型结构。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DURATION_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[smhd])$")
_CLOCK_RE = re.compile(r"^\d{2}:\d{2}$")
_DEFAULT_RESEARCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 stock-news/0.1"
)


class WechatAuthConfig(BaseModel):
    """微信数据源 API 鉴权配置。"""

    type: Literal["none", "bearer", "api_key", "headers"] = "none"
    bearer_token: str = ""
    api_key: str = ""
    api_key_header: str = "Authorization"
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_auth(self) -> WechatAuthConfig:
        if self.type == "bearer" and not self.bearer_token:
            raise ValueError("bearer 鉴权必须配置 bearer_token")
        if self.type == "api_key" and not self.api_key:
            raise ValueError("api_key 鉴权必须配置 api_key")
        if self.type == "headers" and not self.headers:
            raise ValueError("headers 鉴权必须配置 headers")
        return self


class WechatFetchConfig(BaseModel):
    """微信数据源拉取默认参数。"""

    slice_hours: int = 1
    workers: int = 4
    retries: int = 1
    safety_margin_minutes: int = 5

    @model_validator(mode="after")
    def _validate_fetch_defaults(self) -> WechatFetchConfig:
        if self.slice_hours < 1:
            raise ValueError("slice_hours 必须大于等于 1")
        if self.workers < 1:
            raise ValueError("workers 必须大于等于 1")
        if self.retries < 0:
            raise ValueError("retries 必须大于等于 0")
        if self.safety_margin_minutes < 0:
            raise ValueError("safety_margin_minutes 必须大于等于 0")
        return self


class WechatSourceConfig(BaseModel):
    """微信数据源配置。"""

    base_url: str = "https://example.com/api"
    db_path: str = "~/.config/stock-news/wechat.db"
    sources: list[str] = Field(default_factory=lambda: ["个人消息", "个人群"])
    timeout: int = 30
    auth: WechatAuthConfig = Field(default_factory=WechatAuthConfig)
    fetch: WechatFetchConfig = Field(default_factory=WechatFetchConfig)


class LLMProviderConfig(BaseModel):
    """单个模型供应商配置。"""

    base_url: str
    api_key: str = ""
    model: str
    api: Literal["openai", "openai-completions", "anthropic-messages"] = "openai"
    headers: dict[str, str] = Field(default_factory=dict)
    max_tokens: int | None = None
    temperature: float = 0.1
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    timeout: float = 300.0


class LLMConfig(BaseModel):
    """模型供应商总配置。"""

    default_provider: str = ""
    providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    task_routing: dict[str, str] = Field(default_factory=dict)
    provider_pools: dict[str, list[str]] = Field(default_factory=dict)


class TushareConfig(BaseModel):
    """Tushare 代理配置。"""

    tushare_api_url: str = ""
    token: str = ""
    db_path: str = "~/.config/stock-news/market.db"
    timeout: int = 30


class ResearchSourceProviderConfig(BaseModel):
    """单个公开研究源抓取配置。"""

    name: str
    enabled: bool = True
    sitemap_urls: list[str] = Field(default_factory=list)
    url_prefixes: list[str] = Field(default_factory=list)
    url_keywords: list[str] = Field(default_factory=list)
    content_keywords: list[str] = Field(default_factory=list)
    exclude_url_keywords: list[str] = Field(default_factory=list)
    max_pages_per_run: int | None = None

    @model_validator(mode="after")
    def _validate_research_source(self) -> ResearchSourceProviderConfig:
        if self.enabled and not self.sitemap_urls:
            raise ValueError("研究源启用时必须配置 sitemap_urls")
        if self.max_pages_per_run is not None and self.max_pages_per_run < 1:
            raise ValueError("max_pages_per_run 必须大于等于 1")
        return self


class ResearchSourcesConfig(BaseModel):
    """公开研究源抓取配置。"""

    enabled: bool = True
    db_path: str = "~/.config/stock-news/research_sources.db"
    data_dir: str = "~/.config/stock-news/data/research_sources"
    timeout: int = 20
    user_agent: str = _DEFAULT_RESEARCH_USER_AGENT
    max_pages_per_run: int = 20
    sources: dict[str, ResearchSourceProviderConfig] = Field(
        default_factory=lambda: {
            "goldman_sachs": ResearchSourceProviderConfig(
                name="高盛",
                sitemap_urls=["https://www.goldmansachs.com/sitemap.xml"],
                url_prefixes=[
                    "https://www.goldmansachs.com/insights/articles/",
                    "https://www.goldmansachs.com/insights/goldman-sachs-exchanges/",
                    "https://www.goldmansachs.com/insights/top-of-mind/",
                    "https://www.goldmansachs.com/briefings/",
                    "https://www.goldmansachs.com/insights/artificial-intelligence",
                ],
                url_keywords=_default_ai_url_keywords(),
                content_keywords=_default_ai_content_keywords(),
                exclude_url_keywords=["/careers/", "/login"],
            ),
            "citi": ResearchSourceProviderConfig(
                name="花旗",
                sitemap_urls=["https://www.citigroup.com/global/sitemap.xml"],
                url_prefixes=[
                    "https://www.citigroup.com/global/insights/",
                    "https://www.citigroup.com/global/news/press-release/",
                    "https://www.citigroup.com/global/news/perspectives/",
                ],
                url_keywords=_default_ai_url_keywords()
                + ["citi-gps", "gps", "supply-chain-financing"],
                content_keywords=_default_ai_content_keywords() + ["Citi GPS"],
                exclude_url_keywords=["/login", "/unsubscribe"],
            ),
            "jpmorgan": ResearchSourceProviderConfig(
                name="摩根大通",
                sitemap_urls=["https://www.jpmorgan.com/US/en/sitemap.xml"],
                url_prefixes=[
                    "https://www.jpmorgan.com/insights/global-research/artificial-intelligence",
                    "https://www.jpmorgan.com/insights/technology/artificial-intelligence",
                    "https://www.jpmorgan.com/payments/newsroom/",
                    "https://www.jpmorgan.com/insights/podcast-hub/making-sense/",
                ],
                url_keywords=_default_ai_url_keywords(),
                content_keywords=_default_ai_content_keywords(),
                exclude_url_keywords=["/login", "/careers/"],
            ),
            "jpmorgan_asset_management": ResearchSourceProviderConfig(
                name="摩根大通资管",
                sitemap_urls=[
                    "https://am.jpmorgan.com/us/en/asset-management/adv/sitemap.xml",
                    "https://am.jpmorgan.com/sg/en/asset-management/per/sitemap.xml",
                ],
                url_prefixes=[
                    "https://am.jpmorgan.com/us/en/asset-management/",
                    "https://am.jpmorgan.com/sg/en/asset-management/",
                    "https://am.jpmorgan.com/hk/en/asset-management/",
                    "https://am.jpmorgan.com/content/dam/jpm-am-aem/",
                ],
                url_keywords=_default_ai_url_keywords()
                + ["technology-and-ai", "global-ai", "ai-investment"],
                content_keywords=_default_ai_content_keywords(),
                exclude_url_keywords=[
                    "/noindex/",
                    "/login",
                    "/termsofuse",
                    "print.asp",
                    "save.asp",
                ],
            ),
            "morgan_stanley": ResearchSourceProviderConfig(
                name="摩根士丹利",
                sitemap_urls=["https://www.morganstanley.com/sitemap.xml"],
                url_prefixes=[
                    "https://www.morganstanley.com/insights/topics/artificial-intelligence",
                    "https://www.morganstanley.com/insights/articles/",
                    "https://www.morganstanley.com/insights/podcasts/thoughts-on-the-market/",
                    "https://www.morganstanley.com/ideas/",
                ],
                url_keywords=_default_ai_url_keywords(),
                content_keywords=_default_ai_content_keywords(),
                exclude_url_keywords=["/auth/", "/careers/"],
            ),
        }
    )

    @model_validator(mode="after")
    def _validate_research_sources(self) -> ResearchSourcesConfig:
        if self.timeout < 1:
            raise ValueError("timeout 必须大于等于 1")
        if self.max_pages_per_run < 1:
            raise ValueError("max_pages_per_run 必须大于等于 1")
        return self


class AlyConfig(BaseModel):
    """阿里云文件生成和发布配置。"""

    host: str = ""
    user: str = "root"
    password: str = ""
    port: int = 22
    remote_dir: str = ""
    url_prefix: str = ""
    sshpass_path: str = "sshpass"


class ScheduleWechatFetchConfig(BaseModel):
    """微信数据源定时拉取配置。"""

    enabled: bool = True
    every: str = "30m"
    window: str = "30m"

    @model_validator(mode="after")
    def _validate_wechat_fetch(self) -> ScheduleWechatFetchConfig:
        _validate_duration(self.every)
        _validate_duration(self.window)
        return self


class ScheduleTushareSyncConfig(BaseModel):
    """Tushare 股票基础信息定时同步配置。"""

    enabled: bool = True
    at: str = "08:30"

    @model_validator(mode="after")
    def _validate_tushare_sync(self) -> ScheduleTushareSyncConfig:
        _validate_clock(self.at)
        return self


class ScheduleCatalystStockExcelConfig(BaseModel):
    """催化标的 Excel 定时任务配置。"""

    enabled: bool = True
    every: str = "1h"
    window: str = "1h"
    active_start: str = "09:00"
    active_end: str = "23:00"
    channel_targets: list[str] = Field(
        default_factory=lambda: ["dreamboys", "wecom-push-1"]
    )
    channel_routes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_catalyst_stock_excel(self) -> ScheduleCatalystStockExcelConfig:
        _validate_duration(self.every)
        _validate_duration(self.window)
        _validate_clock(self.active_start)
        _validate_clock(self.active_end)
        return self


class ScheduleEveningTopLogicConfig(BaseModel):
    """晚间 Top 投研逻辑定时任务配置。"""

    enabled: bool = True
    at: str = "21:00"
    window_start: str = "09:00"
    window_end: str = "21:00"
    provider: str = "mimo"
    thinking_enabled: bool = True
    thinking_budget_tokens: int | None = None
    top_candidates: int = 50
    top_final: int = 32
    channel_targets: list[str] = Field(
        default_factory=lambda: ["dreamboys", "wecom-push-2"]
    )
    channel_routes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evening_top_logic(self) -> ScheduleEveningTopLogicConfig:
        _validate_clock(self.at)
        _validate_clock(self.window_start)
        _validate_clock(self.window_end)
        if self.top_candidates < 1:
            raise ValueError("top_candidates 必须大于等于 1")
        if self.top_final < 1:
            raise ValueError("top_final 必须大于等于 1")
        if self.top_final > self.top_candidates:
            raise ValueError("top_final 不能大于 top_candidates")
        if self.thinking_budget_tokens is not None and self.thinking_budget_tokens < 1:
            raise ValueError("thinking_budget_tokens 必须大于等于 1")
        return self


class ScheduleResearchDailyBriefConfig(BaseModel):
    """公开研究源每日摘要定时任务配置。"""

    enabled: bool = True
    at: str = "21:30"
    provider: str = "mimo"
    thinking_enabled: bool = True
    thinking_budget_tokens: int | None = None
    lookback_hours: int = 48
    max_pages: int = 20
    max_documents: int = 30
    max_chars_per_document: int = 3500
    channel_targets: list[str] = Field(
        default_factory=lambda: ["dreamboys", "wecom-push-2"]
    )
    channel_routes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_research_daily_brief(self) -> ScheduleResearchDailyBriefConfig:
        _validate_clock(self.at)
        if self.lookback_hours < 1:
            raise ValueError("lookback_hours 必须大于等于 1")
        if self.max_pages < 1:
            raise ValueError("max_pages 必须大于等于 1")
        if self.max_documents < 1:
            raise ValueError("max_documents 必须大于等于 1")
        if self.max_chars_per_document < 200:
            raise ValueError("max_chars_per_document 必须大于等于 200")
        if self.thinking_budget_tokens is not None and self.thinking_budget_tokens < 1:
            raise ValueError("thinking_budget_tokens 必须大于等于 1")
        return self


class ScheduleConfig(BaseModel):
    """定时任务配置文件。"""

    enabled: bool = True
    tick_interval: str = "30s"
    wechat_fetch: ScheduleWechatFetchConfig = Field(
        default_factory=ScheduleWechatFetchConfig
    )
    tushare_sync: ScheduleTushareSyncConfig = Field(
        default_factory=ScheduleTushareSyncConfig
    )
    catalyst_stock_excel: ScheduleCatalystStockExcelConfig = Field(
        default_factory=ScheduleCatalystStockExcelConfig
    )
    evening_top_logic: ScheduleEveningTopLogicConfig = Field(
        default_factory=ScheduleEveningTopLogicConfig
    )
    research_daily_brief: ScheduleResearchDailyBriefConfig = Field(
        default_factory=ScheduleResearchDailyBriefConfig
    )

    @model_validator(mode="after")
    def _validate_schedule_file(self) -> ScheduleConfig:
        _validate_duration(self.tick_interval)
        return self


class DeliveryProviderConfig(BaseModel):
    """单个渠道 provider 配置。"""

    type: Literal["feishu_bot", "wecom_bot"]
    app_id: str = ""
    app_secret: str = ""
    webhook_url: str = ""
    base_url: str = "https://open.feishu.cn"
    timeout: int = 30

    @model_validator(mode="after")
    def _validate_provider(self) -> DeliveryProviderConfig:
        if self.type == "feishu_bot":
            if not self.app_id or not self.app_secret:
                raise ValueError("feishu_bot provider 必须配置 app_id 和 app_secret")
        elif not self.webhook_url:
            raise ValueError("wecom_bot provider 必须配置 webhook_url")
        return self


class DeliveryTargetConfig(BaseModel):
    """渠道投递目标配置。"""

    provider: str
    kind: Literal["user", "chat", "webhook"]
    id: str | None = None
    email: str | None = None
    name: str | None = None
    resolved_id: str | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> DeliveryTargetConfig:
        if self.kind == "chat":
            if not self.id:
                raise ValueError("chat target 必须配置 id/chat_id")
        elif self.kind == "webhook":
            pass
        elif not any([self.id, self.email, self.name, self.resolved_id]):
            raise ValueError("user target 必须配置 open_id、email、name 或 resolved_id")
        return self


class DeliveryRouteConfig(BaseModel):
    """渠道路由配置。"""

    targets: list[str] = Field(default_factory=list)
    format: Literal["text", "post", "markdown", "markdown_v2"] = "post"
    fail_fast: bool = False


class ChannelConfig(BaseModel):
    """渠道配置，包含 provider、target 和 route。"""

    providers: dict[str, DeliveryProviderConfig] = Field(default_factory=dict)
    targets: dict[str, DeliveryTargetConfig] = Field(default_factory=dict)
    routes: dict[str, DeliveryRouteConfig] = Field(default_factory=dict)


class CatalystCategoryOverrideConfig(BaseModel):
    """内置催化词分类的用户覆盖配置。"""

    enabled: bool = True
    extra_terms: list[str] = Field(default_factory=list)
    disabled_terms: list[str] = Field(default_factory=list)

    @field_validator("extra_terms", "disabled_terms")
    @classmethod
    def _normalize_terms(cls, value: list[str]) -> list[str]:
        return _normalize_terms(value)


class CatalystCustomCategoryConfig(BaseModel):
    """用户自定义催化词分类。"""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#5e6ad2", min_length=1, max_length=32)
    enabled: bool = True
    terms: list[str] = Field(default_factory=list)

    @field_validator("terms")
    @classmethod
    def _normalize_terms(cls, value: list[str]) -> list[str]:
        return _normalize_terms(value)


class CatalystConfig(BaseModel):
    """催化词配置，支持内置词库加用户增量覆盖。"""

    version: int = 1
    builtin_enabled: bool = True
    categories: dict[str, CatalystCategoryOverrideConfig] = Field(default_factory=dict)
    custom_categories: list[CatalystCustomCategoryConfig] = Field(default_factory=list)


class AppConfig(BaseModel):
    """聚合后的应用配置，兼容旧字段名并映射到新分层。"""

    model_config = ConfigDict(extra="ignore")

    models: LLMConfig = Field(default_factory=LLMConfig)
    wechat: WechatSourceConfig = Field(default_factory=WechatSourceConfig)
    tushare: TushareConfig = Field(default_factory=TushareConfig)
    research_sources: ResearchSourcesConfig = Field(
        default_factory=ResearchSourcesConfig
    )
    aly: AlyConfig = Field(default_factory=AlyConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    catalysts: CatalystConfig = Field(default_factory=CatalystConfig)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        aliases = {
            "llm": "models",
            "api": "wechat",
            "market": "tushare",
            "delivery": "channel",
        }
        for old_key, new_key in aliases.items():
            if old_key in migrated and new_key not in migrated:
                migrated[new_key] = migrated[old_key]
        publish = migrated.get("publish")
        if isinstance(publish, dict) and "aly" not in migrated:
            nightly = publish.get("nightly")
            if isinstance(nightly, dict):
                migrated["aly"] = nightly
        return migrated


def _validate_duration(value: str) -> None:
    if not _DURATION_RE.match(value.strip()):
        raise ValueError(f"非法 duration: {value}")


def _validate_clock(value: str) -> None:
    if not _CLOCK_RE.match(value.strip()):
        raise ValueError(f"非法时间格式，期望 HH:MM: {value}")
    datetime.strptime(value, "%H:%M")


def _normalize_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return terms


def _default_ai_url_keywords() -> list[str]:
    return [
        "/ai-",
        "-ai-",
        "artificial-intelligence",
        "artificial_intelligence",
        "generative-ai",
        "generative",
        "genai",
        "gen-ai",
        "agentic",
        "agents",
        "robot",
        "robots",
        "data-center",
        "data-centers",
        "semiconductor",
        "semiconductors",
        "chip",
        "chips",
        "compute",
        "hyperscaler",
        "hyperscalers",
        "power-demand",
        "powering-ai",
        "ai-revolution",
        "ai-capex",
    ]


def _default_ai_content_keywords() -> list[str]:
    return [
        "AI",
        "artificial intelligence",
        "generative AI",
        "GenAI",
        "agentic AI",
        "data center",
        "semiconductor",
        "hyperscaler",
        "AI capex",
        "AI infrastructure",
    ]
