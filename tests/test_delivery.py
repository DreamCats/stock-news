from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from stock_news.cli import main
from stock_news.commands import delivery as delivery_cmd
from stock_news.common import config as config_mod
from stock_news.common.delivery import service as delivery_service
from stock_news.common.delivery.feishu_bot import DeliveryMessage, DeliveryResult


def _isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.yaml")


def test_delivery_config_flow_masks_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "delivery",
            "provider",
            "add-feishu",
            "feishu-main",
            "--app-id",
            "cli_xxx",
            "--app-secret",
            "very-secret",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(
        main,
        [
            "delivery",
            "target",
            "add-user",
            "maifeng",
            "--provider",
            "feishu-main",
            "--email",
            "maifeng@bytedance.com",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(main, ["--json", "delivery", "provider", "list"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["feishu-main"]["app_secret"] != "very-secret"

    result = runner.invoke(main, ["--json", "config", "show"])
    assert result.exit_code == 0
    assert "very-secret" not in result.output


def test_delivery_resolve_email(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    monkeypatch.setattr(
        delivery_cmd,
        "resolve_user_by_email",
        lambda _provider_name, _provider, email: f"ou_{email.split('@')[0]}",
    )
    runner = CliRunner()

    runner.invoke(
        main,
        [
            "delivery",
            "provider",
            "add-feishu",
            "feishu-main",
            "--app-id",
            "cli_xxx",
            "--app-secret",
            "secret",
        ],
    )
    runner.invoke(
        main,
        [
            "delivery",
            "target",
            "add-user",
            "maifeng",
            "--provider",
            "feishu-main",
            "--email",
            "maifeng@bytedance.com",
        ],
    )

    result = runner.invoke(main, ["--json", "delivery", "target", "resolve", "maifeng"])

    assert result.exit_code == 0
    assert json.loads(result.output)["resolved_id"] == "ou_maifeng"


def test_delivery_route_send_fans_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    sent: list[tuple[str, DeliveryMessage]] = []

    def fake_send(
        _provider_name: str,
        _provider: object,
        target_name: str,
        _target: object,
        message: DeliveryMessage,
        *,
        idempotency_key: str | None = None,
    ) -> DeliveryResult:
        assert idempotency_key is None
        sent.append((target_name, message))
        return DeliveryResult(
            target=target_name,
            recipient_type="user",
            recipient_id=f"ou_{target_name}",
            ok=True,
            message_id=f"om_{target_name}",
        )

    monkeypatch.setattr(delivery_service, "send_message", fake_send)
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "delivery",
            "provider",
            "add-feishu",
            "feishu-main",
            "--app-id",
            "cli_xxx",
            "--app-secret",
            "secret",
        ],
    )
    for name in ("maifeng", "boss"):
        runner.invoke(
            main,
            [
                "delivery",
                "target",
                "add-user",
                name,
                "--provider",
                "feishu-main",
                "--open-id",
                f"ou_{name}",
            ],
        )
    runner.invoke(
        main,
        [
            "delivery",
            "route",
            "add",
            "daily",
            "--target",
            "maifeng",
            "--target",
            "boss",
        ],
    )

    result = runner.invoke(
        main,
        ["--json", "delivery", "send", "--route", "daily", "--text", "hello"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["sent"] == 2
    assert [item[0] for item in sent] == ["maifeng", "boss"]


def test_delivery_send_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    sent: list[DeliveryMessage] = []

    def fake_send(
        _provider_name: str,
        _provider: object,
        target_name: str,
        _target: object,
        message: DeliveryMessage,
        *,
        idempotency_key: str | None = None,
    ) -> DeliveryResult:
        sent.append(message)
        return DeliveryResult(
            target=target_name,
            recipient_type="user",
            recipient_id="ou_maifeng",
            ok=True,
        )

    monkeypatch.setattr(delivery_service, "send_message", fake_send)
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "delivery",
            "provider",
            "add-feishu",
            "feishu-main",
            "--app-id",
            "cli_xxx",
            "--app-secret",
            "secret",
        ],
    )
    runner.invoke(
        main,
        [
            "delivery",
            "target",
            "add-user",
            "maifeng",
            "--provider",
            "feishu-main",
            "--open-id",
            "ou_maifeng",
        ],
    )

    result = runner.invoke(
        main,
        [
            "--json",
            "delivery",
            "send",
            "--target",
            "maifeng",
            "--markdown",
            "## 今日摘要\n- A\n- B",
            "--title",
            "日报",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["sent"] == 1
    assert sent[0].format == "markdown"
    assert sent[0].title == "日报"
