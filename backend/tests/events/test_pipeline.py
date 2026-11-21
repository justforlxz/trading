"""事件管线：洋葱执行顺序、中止语义与「加一行即生效」的扩展方式。

管线不碰数据库，也不碰网络；用例构造自己的中间件与假通道，只看执行顺序和是否被
中止。注册表本身也在这里被断言：默认链路就是那四道工序，顺序写在代码里。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.events import DomainEvent, apply_channels, build_pipeline, install, uninstall
from app.events.pipeline import DEFAULT_MIDDLEWARES, Pipeline, PipelineDeps
from app.events.sinks.base import DeliveryResult
from app.events.sinks.registry import DeliveryRecorder, SinkRegistry

MOMENT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class RecordingSink:
    """记下收到的每一条事件。"""

    name = "recording"

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def accepts(self, event: DomainEvent) -> bool:
        return event.kind == "alert"

    async def deliver(self, event: DomainEvent) -> DeliveryResult:
        self.events.append(event)
        return DeliveryResult(channel=self.name, status="delivered")


class MemoryRecorder:
    """不写库的投递台账；断言投递次数与结果。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str | None]] = []

    async def __call__(self, result: DeliveryResult, alert_id: str | None) -> None:
        self.rows.append((result.channel, alert_id))


def test_apply_channels_goes_through_the_installed_pipeline() -> None:
    """通道开关只影响已安装的管线；卸载之后不再有作用对象。"""

    sink = RecordingSink()
    registry = SinkRegistry([sink], recorder=MemoryRecorder())
    pipeline = build_pipeline(sinks=registry)

    async def scenario() -> None:
        install(pipeline)
        try:
            apply_channels([])
            assert registry.channels == ()
            apply_channels(["recording"])
            assert registry.channels == ("recording",)
        finally:
            uninstall()
        apply_channels([])  # 已卸载：什么也不做，也不报错
        assert registry.channels == ("recording",)

    asyncio.run(scenario())


def _registry(sink: RecordingSink, recorder: DeliveryRecorder | None = None) -> SinkRegistry:
    return SinkRegistry([sink], recorder=recorder or MemoryRecorder())


def _alert(alert_id: str = "al_1") -> DomainEvent:
    return DomainEvent(
        kind="alert",
        inst_id="XAAPL-USDT",
        payload={"rule_id": "test_rule", "state": "triggered", "alert": {"id": alert_id}},
        occurred_at=MOMENT,
    )


def _tracer(name: str, log: list[str]):
    async def middleware(_event: DomainEvent, call_next) -> None:
        log.append(f"{name}:in")
        await call_next(_event)
        log.append(f"{name}:out")

    return middleware


def _factory(name: str, log: list[str]):
    def factory(_deps: PipelineDeps) -> Any:
        return _tracer(name, log)

    return factory


def _route(sink: RecordingSink):
    async def middleware(event: DomainEvent, call_next) -> None:
        if sink.accepts(event):
            await sink.deliver(event)
        await call_next(event)

    return middleware


def test_default_registry_is_the_four_documented_stages() -> None:
    """注册表就是契约：增加一步要显式写在列表里，顺序即执行顺序。"""

    names = [factory.__module__.rsplit(".", 1)[-1] for factory in DEFAULT_MIDDLEWARES]

    assert names == ["normalize", "rule_engine", "dedupe", "route"]


def test_middlewares_run_as_an_onion_in_registration_order() -> None:
    log: list[str] = []
    pipeline = Pipeline([_tracer("first", log), _tracer("second", log)])

    asyncio.run(pipeline.run(_alert()))

    assert log == ["first:in", "second:in", "second:out", "first:out"]


def test_not_calling_call_next_stops_the_rest_of_the_chain() -> None:
    """不调用 `call_next` 即中止：后面的中间件与通道都收不到。"""

    log: list[str] = []
    sink = RecordingSink()

    async def stopper(_event: DomainEvent, _call_next) -> None:
        log.append("stopper")

    async def after_stopper(_event: DomainEvent, call_next) -> None:
        log.append("after")
        await call_next(_event)

    asyncio.run(Pipeline([stopper, after_stopper, _route(sink)]).run(_alert()))

    assert log == ["stopper"]
    assert sink.events == []


def test_one_extra_registry_line_is_all_a_new_middleware_needs() -> None:
    """新能力只加一行：默认链路后面追加一个工厂，它就被执行了。"""

    log: list[str] = []
    sink = RecordingSink()
    recorder = MemoryRecorder()
    middlewares = (*DEFAULT_MIDDLEWARES, _factory("extra", log))

    asyncio.run(
        build_pipeline(sinks=_registry(sink, recorder), middlewares=middlewares).run(_alert())
    )

    assert log == ["extra:in", "extra:out"]
    assert [event.kind for event in sink.events] == ["alert"]
    assert recorder.rows == [("recording", "al_1")]
