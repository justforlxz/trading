"""美股 K 线管道的中间件链：算时段、幂等落库、把 K 线交给事件总线。

约定与宏观、通知域相同（洋葱模型），但输入是 `Bar`、末端写 `candles`。这里验证三件
事：`enrich` 按真实时刻算交易时段、`upsert` 重复写不新增行、`publish` 只交出已收盘
的 K 线，并且「落库没成立」必须体现在 `PipelineOutcome` 里。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import Bar, Timeframe
from app.equity import pipeline as pipeline_module
from app.equity.pipeline import PendingBatch, build_pipeline
from app.market import US_EQUITY, asset_session
from tests.equity.conftest import LAST_MINUTE_ET, candle_count, equity_bar


class _Recorder:
    """记录交给事件总线的事件；替代真实的 `emit`（未安装管线时它是空操作）。"""

    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, event: object) -> None:
        self.events.append(event)


def _bar(open_time: datetime, *, bar: str = "1m") -> Bar:
    return Bar(
        inst_id="SPY",
        timeframe=Timeframe.parse(bar),
        open_time=open_time,
        open=Decimal("688.00"),
        high=Decimal("690.00"),
        low=Decimal("687.50"),
        close=Decimal("689.81"),
        volume=Decimal("1000"),
        confirm=True,
        source="yahoo",
    )


def test_enrich_marks_the_real_market_session() -> None:
    """盘后拿到的价格必须标成盘后，不能当成正常时段。"""

    # 美东 2026-11-20 18:00（盘后）与 08:00（盘前）。
    post = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)
    pre = datetime(2026, 11, 20, 13, 0, tzinfo=UTC)
    captured: list[tuple[Bar, ...]] = []

    def capture(item: PendingBatch, call_next: object) -> None:
        captured.append(item.records)

    pipeline = build_pipeline((pipeline_module.enrich, capture))
    pipeline.run(PendingBatch(bars=(_bar(post), _bar(pre))))

    records = captured[0]
    assert [item.market_session for item in records] == [
        asset_session(US_EQUITY, post),
        asset_session(US_EQUITY, pre),
    ]
    assert records[0].market_session == "post"
    assert records[1].market_session == "pre"


def test_upsert_writes_once_and_stays_idempotent() -> None:
    """AC2：同一 `(symbol, bar, open_time, source)` 抓三次只留一行。"""

    pipeline = build_pipeline((pipeline_module.enrich, pipeline_module.upsert))
    bars = (equity_bar(open_time=LAST_MINUTE_ET),)

    outcomes = [pipeline.run(PendingBatch(bars=bars)) for _ in range(3)]

    assert [item.completed for item in outcomes] == [True, True, True]
    assert [item.written for item in outcomes] == [1, 1, 1]
    assert candle_count(symbol="SPY") == 1


def test_publish_emits_one_closed_candle_per_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(pipeline_module, "emit", recorder)
    pipeline = build_pipeline(
        (pipeline_module.enrich, pipeline_module.upsert, pipeline_module.publish)
    )

    outcome = pipeline.run(PendingBatch(bars=(equity_bar(open_time=LAST_MINUTE_ET),)))

    assert outcome.completed is True
    assert outcome.published == 1
    event = recorder.events[0]
    assert event.kind == "candle.closed"
    assert event.inst_id == "SPY"
    assert event.payload["confirm"] is True
    assert event.payload["source"] == "yahoo"
    assert event.payload["bar"] == "1m"
    assert event.payload["close"] == "689.81"
    assert event.payload["market_session"] == "regular"
    assert datetime.fromisoformat(event.payload["open_time"]) == LAST_MINUTE_ET


def test_publish_only_emits_newly_written_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一根 K 线被重复抓到时不再发布：否则下游会把旧 K 线反复当成「刚收盘」。"""

    recorder = _Recorder()
    monkeypatch.setattr(pipeline_module, "emit", recorder)
    pipeline = build_pipeline()

    first = pipeline.run(PendingBatch(bars=(equity_bar(open_time=LAST_MINUTE_ET),)))
    second = pipeline.run(PendingBatch(bars=(equity_bar(open_time=LAST_MINUTE_ET),)))

    assert (first.written, first.published) == (1, 1)
    assert (second.written, second.published) == (1, 0)
    assert len(recorder.events) == 1


def test_pipeline_reports_a_failed_write_instead_of_swallowing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """落库没成立必须让上层记成失败，否则健康组件会显示 ok 而库里一行都没有。"""

    def explode(_rows: object) -> object:
        raise RuntimeError("写库失败")

    monkeypatch.setattr(pipeline_module, "upsert_candles", explode)
    pipeline = build_pipeline((pipeline_module.enrich, pipeline_module.upsert))

    outcome = pipeline.run(PendingBatch(bars=(equity_bar(),)))

    assert outcome.completed is False
    assert outcome.written == 0
    assert "写库失败" in (outcome.error or "")


def test_default_chain_is_enrich_then_upsert_then_publish() -> None:
    assert (
        pipeline_module.enrich,
        pipeline_module.upsert,
        pipeline_module.publish,
    ) == pipeline_module.DEFAULT_MIDDLEWARES
