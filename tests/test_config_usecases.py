"""配置用例测试。"""

from __future__ import annotations

from pathlib import Path

import yaml

from stock_news.core.config import set_nested
from stock_news.models import (
    AppConfig,
    CatalystCategoryOverrideConfig,
    DeliveryProviderConfig,
    LLMProviderConfig,
)
from stock_news.usecases.configs.paths import ConfigPaths
from stock_news.usecases.configs.service import load_app_config, save_app_config
from stock_news.usecases.configs.templates import (
    default_aly_config,
    default_catalysts_config,
    default_channel_config,
    default_model_providers_config,
    default_schedule_config,
    default_tushare_config,
    default_wechat_source_config,
    render_aly_template,
    render_catalysts_template,
    render_channel_template,
    render_model_providers_template,
    render_schedule_template,
    render_tushare_template,
    render_wechat_source_template,
)


def test_split_config_save_writes_owned_files(tmp_path: Path) -> None:
    paths = ConfigPaths.from_legacy_file(tmp_path / "config.yaml")
    cfg = AppConfig()
    cfg.models.default_provider = "glm"
    cfg.models.providers["glm"] = LLMProviderConfig(
        base_url="https://llm.example.com/v1",
        api_key="model-secret",
        model="glm-test",
        api="anthropic-messages",
    )
    cfg.wechat.base_url = "https://wechat.example.com/api"
    cfg.tushare.tushare_api_url = "https://tushare-proxy.example.com"
    cfg.aly.host = "39.106.190.32"
    cfg.aly.password = "aly-secret"
    cfg.aly.remote_dir = "/usr/share/caddy/stock-news"
    cfg.schedule.wechat_fetch.every = "15m"
    cfg.schedule.wechat_fetch.window = "15m"
    cfg.channel.providers["feishu-main"] = DeliveryProviderConfig(
        type="feishu_bot",
        app_id="cli_xxx",
        app_secret="feishu-secret",
    )
    cfg.catalysts.categories["price_supply"] = CatalystCategoryOverrideConfig(
        extra_terms=["抢货"]
    )

    save_app_config(paths, cfg)

    assert paths.model_providers_file.exists()
    assert paths.wechat_source_file.exists()
    assert paths.tushare_file.exists()
    assert paths.aly_file.exists()
    assert paths.schedule_file.exists()
    assert paths.channel_file.exists()
    assert paths.catalysts_file.exists()
    assert not paths.legacy_file.exists()

    loaded = load_app_config(paths)
    assert loaded.models.providers["glm"].api_key == "model-secret"
    assert loaded.wechat.base_url == "https://wechat.example.com/api"
    assert loaded.tushare.tushare_api_url == "https://tushare-proxy.example.com"
    assert loaded.aly.host == "39.106.190.32"
    assert loaded.aly.password == "aly-secret"
    assert loaded.aly.remote_dir == "/usr/share/caddy/stock-news"
    assert loaded.schedule.wechat_fetch.every == "15m"
    assert loaded.schedule.wechat_fetch.window == "15m"
    assert loaded.channel.providers["feishu-main"].app_secret == "feishu-secret"
    assert loaded.catalysts.categories["price_supply"].extra_terms == ["抢货"]


def test_split_config_overrides_legacy_sections(tmp_path: Path) -> None:
    paths = ConfigPaths.from_legacy_file(tmp_path / "config.yaml")
    paths.legacy_file.write_text(
        "api:\n  base_url: https://old.example.com\n"
        "market:\n  tushare_api_url: https://old-tushare.example.com\n"
        "delivery:\n  providers: {}\n",
        encoding="utf-8",
    )
    paths.split_dir.mkdir(parents=True)
    paths.wechat_source_file.write_text(
        "base_url: https://new-wechat.example.com\n"
        "sources:\n"
        "  - 个人消息\n"
        "timeout: 10\n",
        encoding="utf-8",
    )

    loaded = load_app_config(paths)

    assert loaded.wechat.base_url == "https://new-wechat.example.com"
    assert loaded.tushare.tushare_api_url == "https://old-tushare.example.com"


def test_legacy_publish_nightly_maps_to_aly_config(tmp_path: Path) -> None:
    paths = ConfigPaths.from_legacy_file(tmp_path / "config.yaml")
    paths.legacy_file.write_text(
        "publish:\n"
        "  nightly:\n"
        "    host: 39.106.190.32\n"
        "    user: root\n"
        "    password: old-secret\n"
        "    port: 22\n"
        "    remote_dir: /usr/share/caddy/stock-news\n"
        "    url_prefix: http://39.106.190.32/stock-news\n"
        "    sshpass_path: sshpass\n",
        encoding="utf-8",
    )

    loaded = load_app_config(paths)

    assert loaded.aly.host == "39.106.190.32"
    assert loaded.aly.password == "old-secret"
    assert loaded.aly.remote_dir == "/usr/share/caddy/stock-news"
    assert loaded.aly.url_prefix == "http://39.106.190.32/stock-news"


def test_set_nested_accepts_legacy_root_alias() -> None:
    cfg = set_nested(AppConfig(), "llm.default_provider", "glm")

    assert cfg.models.default_provider == "glm"


def test_model_providers_template_matches_schema() -> None:
    cfg = default_model_providers_config()

    assert list(cfg.providers) == ["glm", "kimi", "mimo", "minimax"]
    assert cfg.default_provider == "mimo"
    assert cfg.providers["glm"].api == "anthropic-messages"
    assert cfg.providers["glm"].max_tokens is None
    assert cfg.providers["glm"].thinking_enabled is False
    assert cfg.providers["glm"].thinking_budget_tokens is None
    assert cfg.providers["kimi"].max_tokens == 1024
    assert cfg.providers["kimi"].headers == {
        "User-Agent": "KimiCLI/1.30.0",
        "X-Kimi-Client": "KimiCLI",
        "X-Kimi-Client-Version": "1.30.0",
    }
    assert cfg.providers["kimi"].thinking_enabled is False
    assert cfg.task_routing["classify"] == "glm"
    assert cfg.task_routing["source_extract"] == "kimi"
    assert cfg.provider_pools["source_extract"] == [
        "kimi",
        "glm",
        "mimo",
        "minimax",
    ]

    rendered = render_model_providers_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_wechat_source_template_matches_schema() -> None:
    cfg = default_wechat_source_config()

    assert cfg.base_url == "https://<wechat-api-base-url>"
    assert cfg.db_path == "~/.config/stock-news/wechat.db"
    assert cfg.sources == ["个人消息", "个人群"]
    assert cfg.timeout == 30
    assert cfg.auth.type == "none"
    assert cfg.fetch.slice_hours == 1
    assert cfg.fetch.workers == 4
    assert cfg.fetch.retries == 1

    rendered = render_wechat_source_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_tushare_template_matches_schema() -> None:
    cfg = default_tushare_config()

    assert cfg.tushare_api_url == "https://<tushare-proxy-base-url>"
    assert cfg.token == ""
    assert cfg.db_path == "~/.config/stock-news/market.db"
    assert cfg.timeout == 30

    rendered = render_tushare_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_aly_template_matches_schema() -> None:
    cfg = default_aly_config()

    assert cfg.host == "<aliyun-host>"
    assert cfg.user == "root"
    assert cfg.password == ""
    assert cfg.port == 22
    assert cfg.remote_dir == "/usr/share/caddy/stock-news"
    assert cfg.url_prefix == "http://<aliyun-host>/stock-news"
    assert cfg.sshpass_path == "sshpass"

    rendered = render_aly_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_schedule_template_matches_schema() -> None:
    cfg = default_schedule_config()

    assert cfg.enabled is True
    assert cfg.tick_interval == "30s"
    assert cfg.wechat_fetch.enabled is True
    assert cfg.wechat_fetch.every == "30m"
    assert cfg.wechat_fetch.window == "30m"
    assert cfg.tushare_sync.enabled is True
    assert cfg.tushare_sync.at == "08:30"
    assert cfg.catalyst_stock_excel.enabled is True
    assert cfg.catalyst_stock_excel.every == "1h"
    assert cfg.catalyst_stock_excel.window == "1h"
    assert cfg.catalyst_stock_excel.active_start == "09:00"
    assert cfg.catalyst_stock_excel.active_end == "23:00"
    assert cfg.catalyst_stock_excel.channel_targets == [
        "dreamboys",
        "wecom-push-1",
    ]

    rendered = render_schedule_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_channel_template_matches_schema() -> None:
    cfg = default_channel_config()

    assert set(cfg.providers) == {"feishu-main", "wecom-main"}
    assert cfg.providers["feishu-main"].type == "feishu_bot"
    assert cfg.providers["wecom-main"].type == "wecom_bot"
    assert cfg.targets["feishu-user"].provider == "feishu-main"
    assert cfg.targets["feishu-user"].kind == "user"
    assert cfg.targets["wecom-group"].provider == "wecom-main"
    assert cfg.targets["wecom-group"].kind == "webhook"
    assert cfg.routes["default"].targets == ["feishu-user", "wecom-group"]
    assert cfg.routes["default"].format == "markdown"

    rendered = render_channel_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_catalysts_template_matches_schema() -> None:
    cfg = default_catalysts_config()

    assert cfg.builtin_enabled is True
    assert "price_supply" in cfg.categories
    assert cfg.categories["price_supply"].enabled is True
    assert cfg.categories["price_supply"].extra_terms == []
    assert cfg.custom_categories == []

    rendered = render_catalysts_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg
