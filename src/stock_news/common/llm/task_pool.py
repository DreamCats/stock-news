"""LLM provider pool and batch execution helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Generic, TypeVar

from stock_news.common.exceptions import ConfigError
from stock_news.models import AppConfig

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ProviderBatchResult(Generic[R]):
    batch_index: int
    provider_name: str | None
    result: R


def resolve_provider_pool(
    cfg: AppConfig,
    task: str,
    provider_name: str | None = None,
) -> tuple[str | None, ...]:
    """Resolve a task provider pool with explicit provider > pool > route > default."""
    if provider_name:
        if provider_name not in cfg.llm.providers:
            raise ConfigError(f"LLM provider 不存在: {provider_name}")
        return (provider_name,)

    providers = tuple(cfg.llm.provider_pools.get(task) or ())
    missing = [name for name in providers if name not in cfg.llm.providers]
    if missing:
        raise ConfigError(
            f"{task} provider_pools 包含未配置 provider: " + ",".join(missing)
        )
    if providers:
        return providers

    routed = cfg.llm.task_routing.get(task)
    if routed:
        if routed not in cfg.llm.providers:
            raise ConfigError(f"{task} task_routing 指向未配置 provider: {routed}")
        return (routed,)
    return (None,)


def select_provider(
    providers: tuple[str | None, ...],
    batch_index: int,
) -> str | None:
    """Round-robin provider selection."""
    if not providers:
        return None
    return providers[batch_index % len(providers)]


def chunked(items: Sequence[T], batch_size: int) -> list[list[T]]:
    """Split items into fixed-size batches."""
    if batch_size <= 0:
        raise ValueError("batch_size 必须大于 0")
    return [list(items[i : i + batch_size]) for i in range(0, len(items), batch_size)]


def run_provider_batches(
    batches: Sequence[list[T]],
    providers: tuple[str | None, ...],
    max_workers: int,
    worker: Callable[[list[T], str | None], R],
) -> list[ProviderBatchResult[R]]:
    """Run batches concurrently and attach selected provider metadata."""
    if not batches:
        return []

    workers = max(1, min(max_workers, len(batches)))
    results: list[ProviderBatchResult[R]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures: dict[Future[R], tuple[int, str | None]] = {}
        for batch_index, batch in enumerate(batches):
            provider = select_provider(providers, batch_index)
            futures[executor.submit(worker, batch, provider)] = (batch_index, provider)
        for future in as_completed(futures):
            batch_index, provider = futures[future]
            results.append(
                ProviderBatchResult(
                    batch_index=batch_index,
                    provider_name=provider,
                    result=future.result(),
                )
            )
    return sorted(results, key=lambda item: item.batch_index)
