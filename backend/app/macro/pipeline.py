"""宏观数据管道的中间件链：与通知域同一套洋葱约定，独立实例。

约定只有三条，与 `app/events/pipeline.py` 相同：

1. 中间件签名 `mw(batch, call_next)`；调用 `call_next` 继续向内，不调用即在此中止；
2. 中间件按注册顺序由外向内执行，返回途中可以做事（洋葱）；
3. 链上抛出的异常只记日志，不向调用方传播——一批数据坏掉不能拖垮调度器。

**但「不抛」不等于「成功」**：`run` 返回 `PipelineOutcome`（是否走完整条链、实际写入
多少行、失败原因），调用方必须据此判定落库是否成立。否则末端 `upsert` 写库失败会被
吞掉，上层照样回报 `synced`，故障就被掩盖了。

**不共享 `app/events/pipeline.py` 的代码**：那个执行器持有通知通道注册表并带
`apply_channels`，泛型化等于把「通道」概念从通知域搬出去，而动它是改已交付接口；
这里需要的只是「按顺序穿过去」这 25 行。两套实现的一致性由
`backend/tests/macro/test_pipeline_contract.py` 的参数化用例锁死。

一批观测走完整条链：`enrich` 按 `ts` 算归属交易日与交易时段，`upsert` 按唯一键写库。
新增数据源时只加 Provider 与调度表一行，这条链不动。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.core import Observation
from app.macro.store import ObservationRecord, save_observations
from app.market import (
    EXCHANGE_CLOSED,
    exchange_session,
    from_epoch,
    settlement_epoch,
    trading_day_of,
)

__all__ = [
    "DEFAULT_MIDDLEWARES",
    "CallNext",
    "Middleware",
    "PendingBatch",
    "Pipeline",
    "PipelineOutcome",
    "RunContext",
    "build_pipeline",
    "enrich",
    "upsert",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunContext:
    """一次 `run` 的共享累加器：末端中间件把实际写入行数记在这里。"""

    written: int = 0


@dataclass(frozen=True, slots=True)
class PendingBatch:
    """一次管道输入：原始观测、enrich 之后的版本，以及本次运行的累加器。"""

    observations: tuple[Observation, ...] = field(default_factory=tuple)
    records: tuple[ObservationRecord, ...] = field(default_factory=tuple)
    context: RunContext = field(default_factory=RunContext)


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """一次管道运行的结果；`completed=False` 时 `error` 说明断在哪一步。"""

    completed: bool
    written: int
    error: str | None


CallNext = Callable[[PendingBatch], None]
Middleware = Callable[[PendingBatch, CallNext], None]


class Pipeline:
    """按注册顺序把一批观测穿过全部中间件，并回报落库是否成立。"""

    def __init__(self, middlewares: Sequence[Middleware]) -> None:
        self._middlewares = tuple(middlewares)

    def run(self, batch: PendingBatch) -> PipelineOutcome:
        """处理一批观测；异常只记录不抛出，但会体现在返回的 `PipelineOutcome` 里。"""

        try:
            self._dispatch(batch, 0)
        except Exception as exc:
            logger.exception("宏观数据管道处理失败")
            return PipelineOutcome(
                completed=False,
                written=batch.context.written,
                error=f"{type(exc).__name__}: {exc}",
            )
        return PipelineOutcome(completed=True, written=batch.context.written, error=None)

    def _dispatch(self, batch: PendingBatch, index: int) -> None:
        if index >= len(self._middlewares):
            return
        call_next: CallNext = lambda next_batch: self._dispatch(next_batch, index + 1)  # noqa: E731
        self._middlewares[index](batch, call_next)


def _enrich(item: Observation) -> ObservationRecord:
    """一条观测的派生字段。

    时段分两种：结算值的 `ts` 就是该交易日的收盘时刻（provider 用 `settlement_epoch`
    生成），它天然属于「已收盘」，不需要查休市日表；只有非结算时刻（分钟级读数）才按
    交易日历判断。日更源的历史可以回溯几十年，而休市日表只覆盖有限年份，混用会让整份
    历史结算数据在首次同步时被日历判定拦住。
    """

    moment = from_epoch(item.ts)
    trading_day = trading_day_of(moment)
    settled = item.ts == settlement_epoch(trading_day)
    return ObservationRecord(
        observation=item,
        trading_day=trading_day,
        market_session=EXCHANGE_CLOSED if settled else exchange_session(moment),
    )


def enrich(batch: PendingBatch, call_next: CallNext) -> None:
    """按 `ts` 算归属交易日与交易时段；规则来自 `app.market.session`，不在这里重写。"""

    records = tuple(_enrich(item) for item in batch.observations)
    call_next(
        PendingBatch(
            observations=batch.observations,
            records=records,
            context=batch.context,
        )
    )


def upsert(batch: PendingBatch, call_next: CallNext) -> None:
    """末端中间件：按唯一键写库，写完即结束（不调用 `call_next`）。"""

    batch.context.written = save_observations(batch.records)


#: 中间件注册表：顺序即执行顺序（外层在前）。新能力在这里加一行。
DEFAULT_MIDDLEWARES: tuple[Middleware, ...] = (enrich, upsert)


def build_pipeline(
    middlewares: Sequence[Middleware] = DEFAULT_MIDDLEWARES,
) -> Pipeline:
    """按注册表实例化一条独立管线。"""

    return Pipeline(middlewares)
