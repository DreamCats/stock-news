"""delivery provider/target/route 装配服务."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from stock_news.common.config import load
from stock_news.common.delivery.feishu_bot import (
    DeliveryMessage,
    DeliveryResult,
    send_file_message,
    send_message,
)
from stock_news.common.delivery.wecom_bot import (
    send_file_message as send_wecom_file_message,
)
from stock_news.common.delivery.wecom_bot import send_message as send_wecom_message
from stock_news.common.exceptions import ConfigError
from stock_news.models import (
    DeliveryProviderConfig,
    DeliveryRouteConfig,
    DeliveryTargetConfig,
)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "***"


def provider_data(provider: DeliveryProviderConfig) -> dict[str, object]:
    data = provider.model_dump(mode="json")
    data["app_secret"] = mask_secret(provider.app_secret)
    data["webhook_url"] = "***" if provider.webhook_url else ""
    return data


def load_provider(name: str) -> DeliveryProviderConfig:
    provider = load().delivery.providers.get(name)
    if provider is None:
        raise ConfigError(f"未找到 delivery provider: {name}")
    return provider


def load_target(name: str) -> DeliveryTargetConfig:
    target = load().delivery.targets.get(name)
    if target is None:
        raise ConfigError(f"未找到 delivery target: {name}")
    return target


def ensure_provider_exists(provider_name: str) -> None:
    if provider_name not in load().delivery.providers:
        raise ConfigError(f"未找到 delivery provider: {provider_name}")


def route_targets(route_name: str) -> tuple[DeliveryRouteConfig, list[str]]:
    cfg = load()
    route = cfg.delivery.routes.get(route_name)
    if route is None:
        raise ConfigError(f"未找到 delivery route: {route_name}")
    missing = [name for name in route.targets if name not in cfg.delivery.targets]
    if missing:
        raise ConfigError(f"route 引用了不存在的 target: {', '.join(missing)}")
    return route, route.targets


def send_target(
    target_name: str,
    message: DeliveryMessage,
    idempotency_key: str | None = None,
) -> DeliveryResult:
    target = load_target(target_name)
    provider = load_provider(target.provider)
    if provider.type == "feishu_bot":
        return send_message(
            target.provider,
            provider,
            target_name,
            target,
            message,
            idempotency_key=idempotency_key,
        )
    if provider.type == "wecom_bot":
        return send_wecom_message(provider, target_name, target, message)
    raise ConfigError(f"暂不支持的 delivery provider 类型: {provider.type}")


def send_targets(
    target_names: list[str],
    message: DeliveryMessage,
    *,
    fail_fast: bool = False,
    idempotency_key: str | None = None,
) -> list[DeliveryResult]:
    results: list[DeliveryResult] = []
    for target_name in target_names:
        result = send_target(target_name, message, idempotency_key)
        results.append(result)
        if fail_fast and not result.ok:
            break
    return results


def send_file_target(
    target_name: str,
    file_path: Path,
    idempotency_key: str | None = None,
) -> DeliveryResult:
    target = load_target(target_name)
    provider = load_provider(target.provider)
    if provider.type == "feishu_bot":
        return send_file_message(
            target.provider,
            provider,
            target_name,
            target,
            file_path,
            idempotency_key=idempotency_key,
        )
    if provider.type == "wecom_bot":
        return send_wecom_file_message(provider, target_name, target, file_path)
    return DeliveryResult(
        target=target_name,
        recipient_type=target.kind,
        recipient_id=target.resolved_id or target.id or target_name,
        ok=False,
        error=f"{provider.type} 暂不支持文件附件投递",
    )


def send_file_targets(
    target_names: list[str],
    file_path: Path,
    *,
    fail_fast: bool = False,
    idempotency_key: str | None = None,
) -> list[DeliveryResult]:
    results: list[DeliveryResult] = []
    for target_name in target_names:
        result = send_file_target(target_name, file_path, idempotency_key)
        results.append(result)
        if fail_fast and not result.ok:
            break
    return results


def result_payload(results: list[DeliveryResult]) -> dict[str, object]:
    failed = [r for r in results if not r.ok]
    return {
        "ok": not failed,
        "data": {
            "sent": len(results) - len(failed),
            "failed": len(failed),
            "results": [asdict(result) for result in results],
        },
        "message": f"投递完成，成功 {len(results) - len(failed)}，失败 {len(failed)}",
    }


def targets_data() -> dict[str, dict[str, Any]]:
    return {
        name: target.model_dump(mode="json")
        for name, target in load().delivery.targets.items()
    }


def routes_data() -> dict[str, dict[str, Any]]:
    return {
        name: route.model_dump(mode="json")
        for name, route in load().delivery.routes.items()
    }


def providers_data() -> dict[str, dict[str, object]]:
    return {
        name: provider_data(provider)
        for name, provider in load().delivery.providers.items()
    }
