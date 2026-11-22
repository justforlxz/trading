"""宏观调度器：一个 tick 的抓取范围、日线判重与可观测状态。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core import UpstreamError
from app.jobs import MarketDataScheduler
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
