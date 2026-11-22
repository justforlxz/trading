"""美股 K 线管道的中间件链：与宏观、通知域同一套洋葱约定，独立实例。

约定只有三条，与 `app/macro/pipeline.py` 相同：

1. 中间件签名 `mw(batch, call_next)`；调用 `call_next` 继续向内，不调用即在此中止；
2. 中间件按注册顺序由外向内执行，返回途中可以做事（洋葱）；
3. 链上抛出的异常只记日志，不向调用方传播——一批数据坏掉不能拖垮调度器。

**但「不抛」不等于「成功」**：`run` 返回 `PipelineOutcome`（是否走完整条链、实际写入
多少行、发布了几条事件、失败原因），调用方必须据此判定落库是否成立。否则末端
`upsert` 写库失败会被吞掉，上层照样回报 `synced`，故障就被掩盖了。

**不共享 `app/macro/pipeline.py` 的实现**：那个执行器的输入是 `Observation`、末端写
`macro_observations`；本链的输入是 `Bar`、末端写 `candles`。两者只有「按顺序穿过去」
这 25 行相同，泛型化等于把「宏观观测」与「K 线」两个概念塞进一个类型。一致性由
`backend/tests/equity/test_pipeline_contract.py` 的参数化用例锁死。

一批 K 线走完整条链：`enrich` 按 `open_time` 算交易时段，`upsert` 按唯一键写
`candles`，`publish` 把每根 K 线作为 `candle.closed` 交到事件总线。新增数据源时只加
Provider 与配置一行，这条链不动。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC

from app.core import Bar
from app.equity.store import existing_keys
from app.events import DomainEvent, emit
from app.market import US_EQUITY, asset_session, to_epoch, upsert_candles

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
    "publish",
    "upsert",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunContext:
    """一次 `run` 的共享累加器：中间件把实际写入行数、新写入的行与发布条数记在这里。"""

    written: int = 0
    published: int = 0
    #: 本次真正新写进 `candles` 的 K 线；重复抓到的旧行不进这个列表。
    new_bars: tuple[Bar, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingBatch:
    """一次管道输入：原始 K 线、enrich 之后的版本，以及本次运行的累加器。"""

    bars: tuple[Bar, ...] = field(default_factory=tuple)
    records: tuple[Bar, ...] = field(default_factory=tuple)
    context: RunContext = field(default_factory=RunContext)


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """一次管道运行的结果；`completed=False` 时 `error` 说明断在哪一步。"""

    completed: bool
    written: int
    published: int
    error: str | None


CallNext = Callable[[PendingBatch], None]
Middleware = Callable[[PendingBatch, CallNext], None]


class Pipeline:
    """按注册顺序把一批 K 线穿过全部中间件，并回报落库与发布是否成立。"""

    def __init__(self, middlewares: Sequence[Middleware]) -> None:
        self._middlewares = tuple(middlewares)

    def run(self, batch: PendingBatch) -> PipelineOutcome:
        """处理一批 K 线；异常只记录不抛出，但会体现在返回的 `PipelineOutcome` 里。"""

        try:
            self._dispatch(batch, 0)
        except Exception as exc:
            logger.exception("美股 K 线管道处理失败")
            return PipelineOutcome(
                completed=False,
                written=batch.context.written,
                published=batch.context.published,
                error=f"{type(exc).__name__}: {exc}",
            )
        return PipelineOutcome(
            completed=True,
            written=batch.context.written,
            published=batch.context.published,
            error=None,
        )

    def _dispatch(self, batch: PendingBatch, index: int) -> None:
        if index >= len(self._middlewares):
            return
        call_next: CallNext = lambda next_batch: self._dispatch(next_batch, index + 1)  # noqa: E731
        self._middlewares[index](batch, call_next)


def enrich(batch: PendingBatch, call_next: CallNext) -> None:
    """按 `open_time` 算交易时段；规则来自 `app.market.session`，不在这里重写。

    美股标的的时段有盘前 / 正常 / 盘后 / 休市四种，必须按真实时刻算：把盘后拿到的
    价格标成「正常时段」就是伪造交易时段。
    """

    records = tuple(
        replace(item, market_session=asset_session(US_EQUITY, item.open_time))
        for item in batch.bars
    )
    call_next(PendingBatch(bars=batch.bars, records=records, context=batch.context))


def _key(bar: Bar) -> tuple[str, str, int, str]:
    return (bar.inst_id, bar.timeframe.value, to_epoch(bar.open_time), bar.source)


def upsert(batch: PendingBatch, call_next: CallNext) -> None:
    """按 `(symbol, bar, open_time, source)` 唯一键写库；重复抓取不新增行。

    写入前先查一遍这批行里哪些已经存在：一次抓取的窗口覆盖整个交易日，其中绝大多数
    是上一分钟已经写过的同一根，只有真正新写入的才该继续往事件总线走。
    """

    existing = existing_keys(batch.records)
    batch.context.new_bars = tuple(item for item in batch.records if _key(item) not in existing)
    result = upsert_candles(batch.records)
    batch.context.written = result.inserted + result.updated
    call_next(batch)


def publish(batch: PendingBatch, call_next: CallNext) -> None:
    """把**本次新写入**的 K 线交给事件总线；没有安装管线时 `emit` 什么也不做。

    只发布新行：同一根 K 线每分钟都被重新抓到一次，重复发布会让下游把一根旧 K 线反复
    当成「刚收盘」，`published` 也会虚高。只交出已收盘的 K 线——未收盘的价格还会变，
    当事实会产生「事后被改写的提醒」。
    """

    for bar in batch.context.new_bars:
        emit(
            DomainEvent(
                kind="candle.closed",
                inst_id=bar.inst_id,
                payload={
                    "bar": bar.timeframe.value,
                    "open_time": bar.open_time.astimezone(UTC).isoformat(),
                    "open": format(bar.open, "f"),
                    "high": format(bar.high, "f"),
                    "low": format(bar.low, "f"),
                    "close": format(bar.close, "f"),
                    "volume": format(bar.volume, "f"),
                    "confirm": True,
                    "source": bar.source,
                    "market_session": bar.market_session,
                },
                occurred_at=bar.open_time,
            )
        )
    batch.context.published = len(batch.context.new_bars)
    call_next(batch)


#: 中间件注册表：顺序即执行顺序（外层在前）。新能力在这里加一行。
DEFAULT_MIDDLEWARES: tuple[Middleware, ...] = (enrich, upsert, publish)


def build_pipeline(
    middlewares: Sequence[Middleware] = DEFAULT_MIDDLEWARES,
) -> Pipeline:
    """按注册表实例化一条独立管线。"""

    return Pipeline(middlewares)
