"""配置用例测试。"""

from __future__ import annotations

from pathlib import Path

import yaml

from stock_news.common.config import set_nested
from stock_news.models import (
    AppConfig,
    DeliveryProviderConfig,
    LLMProviderConfig,
    ScheduleJobConfig,
)
from stock_news.usecases.configs.paths import ConfigPaths
from stock_news.usecases.configs.service import load_app_config, save_app_config
from stock_news.usecases.configs.templates import (
    default_channel_config,
    default_model_providers_config,
    default_schedule_config,
    default_tushare_config,
    default_wechat_source_config,
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
    cfg.schedule.jobs.append(
        ScheduleJobConfig(id="wechat-fetch", command="sn fetch-wechat", every="5m")
    )
    cfg.channel.providers["feishu-main"] = DeliveryProviderConfig(
        type="feishu_bot",
        app_id="cli_xxx",
        app_secret="feishu-secret",
    )

    save_app_config(paths, cfg)

    assert paths.model_providers_file.exists()
    assert paths.wechat_source_file.exists()
    assert paths.tushare_file.exists()
    assert paths.schedule_file.exists()
    assert paths.channel_file.exists()
    assert not paths.legacy_file.exists()

    loaded = load_app_config(paths)
    assert loaded.models.providers["glm"].api_key == "model-secret"
    assert loaded.wechat.base_url == "https://wechat.example.com/api"
    assert loaded.tushare.tushare_api_url == "https://tushare-proxy.example.com"
    assert loaded.schedule.jobs[0].id == "wechat-fetch"
    assert loaded.channel.providers["feishu-main"].app_secret == "feishu-secret"


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


def test_set_nested_accepts_legacy_root_alias() -> None:
    cfg = set_nested(AppConfig(), "llm.default_provider", "glm")

    assert cfg.models.default_provider == "glm"


def test_model_providers_template_matches_schema() -> None:
    cfg = default_model_providers_config()

    assert list(cfg.providers) == ["glm", "kimi", "mimo", "minimax"]
    assert cfg.default_provider == "mimo"
    assert cfg.providers["glm"].api == "anthropic-messages"
    assert cfg.providers["glm"].max_tokens is None
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
    assert cfg.timeout == 30

    rendered = render_tushare_template()
    parsed = yaml.safe_load(rendered)
    loaded = type(cfg).model_validate(parsed)
    assert loaded == cfg


def test_schedule_template_matches_schema() -> None:
    cfg = default_schedule_config()

    assert cfg.tick_interval == "5m"
    assert cfg.jobs == []

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
