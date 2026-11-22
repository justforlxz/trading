"""两套同步 Pipeline 的约定一致性。

同一组参数化用例分别跑 `app/events/pipeline.py`（异步，参考实现）与
`app/equity/pipeline.py`（同步，本单新增）：中间件按注册顺序执行、不调用 `call_next`
即中止、中间件抛异常不向调用方传播。两份实现不共享代码，靠这组用例锁住「同一套洋葱
模型」这个承诺。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.equity.pipeline import PendingBatch
from app.equity.pipeline import Pipeline as EquityPipeline
from app.events.event import DomainEvent
from app.events.pipeline import Pipeline as EventsPipeline

Options = dict[str, bool]


def sync_middleware(order: list[str], label: str, options: Options):
    def _run(item: Any, call_next: Callable[[Any], None]) -> None:
        order.append(f"{label}>")
        if options.get("explode"):
            raise RuntimeError(f"{label} 炸了")
        if options.get("stop"):
            return
        call_next(item)
        order.append(f"{label}<")

    return _run


def async_middleware(order: list[str], label: str, options: Options):
    async def _run(item: Any, call_next: Callable[[Any], Awaitable[None]]) -> None:
        order.append(f"{label}>")
        if options.get("explode"):
            raise RuntimeError(f"{label} 炸了")
        if options.get("stop"):
            return
        await call_next(item)
        order.append(f"{label}<")

    return _run


def _run_async(pipeline: Any, item: Any) -> None:
    asyncio.run(pipeline.run(item))


def _run_sync(pipeline: Any, item: Any) -> None:
    pipeline.run(item)


#: (名字, 构造, 中间件工厂, 输入, 执行)
PIPELINES = (
    (
        "events",
        lambda middlewares: EventsPipeline(list(middlewares)),
        async_middleware,
        lambda: DomainEvent(kind="quote", inst_id=None),
        _run_async,
    ),
    (
        "equity",
        lambda middlewares: EquityPipeline(list(middlewares)),
        sync_middleware,
        lambda: PendingBatch(),
        _run_sync,
    ),
)


def _ids(cases):
    return [case[0] for case in cases]


@pytest.mark.parametrize(
    ("name", "build", "middleware", "item_factory", "run"),
    PIPELINES,
    ids=_ids(PIPELINES),
)
def test_middlewares_run_in_registration_order(
    name: str,
    build: Callable[..., Any],
    middleware: Callable[..., Any],
    item_factory: Callable[[], Any],
    run: Callable[[Any, Any], None],
) -> None:
    order: list[str] = []
    pipeline = build([middleware(order, "outer", {}), middleware(order, "inner", {})])

    run(pipeline, item_factory())

    assert order == ["outer>", "inner>", "inner<", "outer<"]


@pytest.mark.parametrize(
    ("name", "build", "middleware", "item_factory", "run"),
    PIPELINES,
    ids=_ids(PIPELINES),
)
def test_not_calling_next_stops_the_chain(
    name: str,
    build: Callable[..., Any],
    middleware: Callable[..., Any],
    item_factory: Callable[[], Any],
    run: Callable[[Any, Any], None],
) -> None:
    order: list[str] = []
    pipeline = build([middleware(order, "outer", {"stop": True}), middleware(order, "inner", {})])

    run(pipeline, item_factory())

    assert order == ["outer>"]


@pytest.mark.parametrize(
    ("name", "build", "middleware", "item_factory", "run"),
    PIPELINES,
    ids=_ids(PIPELINES),
)
def test_middleware_error_does_not_propagate(
    name: str,
    build: Callable[..., Any],
    middleware: Callable[..., Any],
    item_factory: Callable[[], Any],
    run: Callable[[Any, Any], None],
) -> None:
    order: list[str] = []
    pipeline = build([middleware(order, "boom", {"explode": True})])

    run(pipeline, item_factory())  # 不抛异常即为通过

    assert order == ["boom>"]
