"""宏观调度器：一个 tick 的抓取范围、日线判重与可观测状态。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core import UpstreamError
from app.equity import SyncResult as EquitySyncResult
from app.jobs import MarketDataScheduler
from app.jobs import market_data as jobs_module
from app.macro import SyncResult
from app.macro import service as service_module
from app.market import settlement_epoch
from tests.macro.conftest import FakeProvider, observation, provider_builder

DAY = date(2026, 11, 20)
TS = settlement_epoch(DAY)
NOW = datetime(2026, 11, 22, 7, 1, tzinfo=UTC)


def _record(provider: FakeProvider, calls: list[tuple[str, ...]]) -> FakeProvider:
    """把每次 fetch 记到调用方列表里，便于断言「第二次 tick 没再请求日线」。"""

    original = provider.fetch

    def fetch(series, since):
        calls.append(tuple(series))
        return original(series, since)

    provider.fetch = fetch  # type: ignore[method-assign]
    return provider


def _values() -> dict[str, list]:
    return {
        "us10y": [
            observation("us10y", ts=TS, value="4.92", provider="treasury"),
            observation("us10y", ts=TS + 3600, value="4.90", provider="yahoo"),
        ],
        "us2y": [observation("us2y", ts=TS, value="4.63", provider="treasury")],
        "vix": [
            observation("vix", ts=TS, value="35.89", provider="cboe"),
            observation("vix", ts=TS + 3600, value="35.90", provider="yahoo"),
        ],
    }


def test_tick_runs_every_unit_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    builder = provider_builder(_values())
    monkeypatch.setattr(
        service_module,
        "build_provider",
        lambda name, **_: _record(builder(name, **_), calls),
    )
    scheduler = MarketDataScheduler()

    results = scheduler.run_once(now=NOW)

    assert [(item.series_id, item.granularity) for item in results] == [
        ("us10y", "minute"),
        ("us10y", "daily"),
        ("us2y", "daily"),
        ("vix", "minute"),
        ("vix", "daily"),
    ]
    assert {item.status for item in results} == {"synced"}

    status = scheduler.status_snapshot()
    assert status["last_run_at"] == "2026-11-22T07:01:00Z"
    assert status["next_run_at"] == "2026-11-22T07:02:00Z"
    assert isinstance(status["duration_ms"], int)
    assert status["last_success_at"] is not None
    assert status["degraded"] is False


def test_tick_skips_daily_source_already_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    builder = provider_builder(_values())
    monkeypatch.setattr(
        service_module,
        "build_provider",
        lambda name, **_: _record(builder(name, **_), calls),
    )
    scheduler = MarketDataScheduler()

    scheduler.run_once(now=NOW)
    calls_after_first = len(calls)
    second = scheduler.run_once(now=NOW + timedelta(seconds=61))

    daily = [item for item in second if item.granularity == "daily"]
    assert [item.status for item in daily] == ["unchanged", "unchanged", "unchanged"]
    # 第二次 tick 只为分钟级单元请求上游：日线结算源该日已有观测就不发请求。
    assert len(calls) - calls_after_first == 2


def test_tick_marks_failures_and_reports_them(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        name = "fake"

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series: object, since: object) -> list[object]:
            raise UpstreamError("上游 503")

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: Failing())
    scheduler = MarketDataScheduler()

    # 失败后退避 1×/2×/4× 周期；窗口内的 tick 不再打上游，所以要把时间推过去。
    scheduler.run_once(now=NOW)
    scheduler.run_once(now=NOW + timedelta(seconds=61))
    scheduler.run_once(now=NOW + timedelta(seconds=61 + 121))

    status = scheduler.status_snapshot()
    assert status["degraded"] is True
    assert "503" in (status["last_error"] or "")
    series = {item["series_id"]: item for item in status["series"]}
    assert series["vix"]["failures"] == 3
    assert series["vix"]["degraded"] is True


def test_tick_inside_backoff_does_not_call_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    class Failing:
        name = "fake"

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series, since):
            calls.append(tuple(series))
            raise UpstreamError("上游 503")

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: Failing())
    scheduler = MarketDataScheduler()

    scheduler.run_once(now=NOW)
    calls_after_first = len(calls)
    results = scheduler.run_once(now=NOW + timedelta(seconds=10))

    assert {item.status for item in results} == {"skipped"}
    assert len(calls) == calls_after_first


def test_failed_unit_does_not_block_other_series(monkeypatch: pytest.MonkeyPatch) -> None:
    class OnlyVixFails:
        def __init__(self, name: str) -> None:
            self.name = name
            self.inner = FakeProvider(name, _values())

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series, since):
            if "vix" in series:
                raise UpstreamError("VIX 源不可用")
            return self.inner.fetch(series, since)

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: OnlyVixFails(name))
    scheduler = MarketDataScheduler()

    results = scheduler.run_once(now=NOW)

    by_key = {(item.series_id, item.granularity): item.status for item in results}
    assert by_key[("vix", "minute")] == "failed"
    assert by_key[("us10y", "minute")] == "synced"
    assert by_key[("us2y", "daily")] == "synced"


def test_scheduler_reports_unconfigured_before_first_tick() -> None:
    status = MarketDataScheduler().status_snapshot()

    assert status["last_run_at"] is None
    assert status["last_success_at"] is None
    assert status["degraded"] is False
    assert status["series"] == []


def test_scheduler_plans_next_before_first_tick() -> None:
    """首次 tick 要等一个周期；启动后就该有「下次计划」，健康组件不必等第一次运行。"""

    scheduler = MarketDataScheduler()
    try:
        scheduler.start()
        status = scheduler.status_snapshot()
    finally:
        scheduler.shutdown()

    assert status["last_run_at"] is None
    assert status["next_run_at"] is not None


def test_equity_tick_records_its_own_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """美股 tick 与宏观分开记状态：最近运行、下次计划与耗时都可读。"""

    from app.equity import reset_runtime as reset_equity_runtime
    from app.equity import runtime as equity_runtime
    from app.equity import service as equity_service

    recorded: list[tuple[object, object]] = []

    def fake_sync(**_: object):
        recorded.append(("sync", None))
        return ()

    reset_equity_runtime()
    monkeypatch.setattr(equity_service, "sync", fake_sync)
    monkeypatch.setattr(
        "app.jobs.market_data.equity_sync",
        fake_sync,
    )

    try:
        scheduler = MarketDataScheduler()
        results = scheduler.run_equity_once(now=NOW)
        status = scheduler.equity_status_snapshot()
    finally:
        reset_equity_runtime()

    assert results == ()
    assert recorded == [("sync", None)]
    assert status["last_run_at"] == "2026-11-22T07:01:00Z"
    assert status["next_run_at"] is not None
    assert status["duration_ms"] is not None
    assert equity_runtime().status()["last_run_at"] is None  # 重置后回到空状态


def test_equity_tick_failure_does_not_block_the_macro_tick() -> None:
    """一个域抛异常不能拖累另一个域：`_tick` 分别兜住。"""

    scheduler = MarketDataScheduler()
    calls: list[str] = []

    def broken_macro(**_: object) -> None:
        calls.append("macro")
        raise RuntimeError("宏观配置写坏了")

    def ok_equity(**_: object) -> tuple[()]:
        calls.append("equity")
        return ()

    scheduler.run_once = broken_macro  # type: ignore[method-assign]
    scheduler.run_equity_once = ok_equity  # type: ignore[method-assign]

    scheduler._tick()

    assert calls == ["macro", "equity"]


def _equity_result(*, bar: str, published: int) -> EquitySyncResult:
    return EquitySyncResult(
        provider="yahoo", bar=bar, status="synced", rows=1, published=published, error=None
    )


def test_a_new_daily_bar_triggers_the_market_alert_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7：大盘/组合异动挂在行情调度轮次上，不新增定时器。

    触发条件是「这一轮真的收到了新的收盘数据」：分钟级每分钟都在写，不能每分钟都评估
    一遍日线规则。
    """

    scheduler = MarketDataScheduler()
    scans: list[str] = []
    monkeypatch.setattr(scheduler, "run_once", lambda **_: ())
    monkeypatch.setattr(
        scheduler,
        "run_equity_once",
        lambda **_: (
            _equity_result(bar="1m", published=1),
            _equity_result(bar="1d", published=1),
        ),
    )
    monkeypatch.setattr(scheduler, "run_market_alert_scan", lambda: scans.append("scan"))

    scheduler._tick()

    assert scans == ["scan"]


def test_a_tick_without_new_daily_data_does_not_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有分钟级新行时不评估：日线一天只变一次。"""

    scheduler = MarketDataScheduler()
    scans: list[str] = []
    monkeypatch.setattr(scheduler, "run_once", lambda **_: ())
    monkeypatch.setattr(
        scheduler,
        "run_equity_once",
        lambda **_: (
            _equity_result(bar="1m", published=5),
            _equity_result(bar="1d", published=0),
        ),
    )
    monkeypatch.setattr(scheduler, "run_market_alert_scan", lambda: scans.append("scan"))

    scheduler._tick()

    assert scans == []


def test_a_new_macro_settlement_also_triggers_the_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """宏观日结值落地同样触发：10Y 与利差规则的数据来自宏观域。"""

    scheduler = MarketDataScheduler()
    scans: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "run_once",
        lambda **_: (
            SyncResult(
                series_id="us10y",
                granularity="daily",
                provider="treasury",
                status="synced",
                rows=1,
                error=None,
            ),
        ),
    )
    monkeypatch.setattr(scheduler, "run_equity_once", lambda **_: ())
    monkeypatch.setattr(scheduler, "run_market_alert_scan", lambda: scans.append("scan"))

    scheduler._tick()

    assert scans == ["scan"]


def test_a_failing_scan_does_not_kill_the_scheduler_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫描失败只记日志：调度线程不能因为一条提醒挂掉。"""

    def broken(**_: object) -> None:
        raise RuntimeError("数据库不可用")

    monkeypatch.setattr(jobs_module, "scan_market_alerts", broken)

    # 不抛异常即通过：失败在 `run_market_alert_scan` 里被兜住并记日志。
    MarketDataScheduler().run_market_alert_scan()
