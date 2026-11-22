"""宏观服务：幂等落库、只读总览、降级、退避与利差口径。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import UpstreamError
from app.db import session_scope
from app.macro import macro_overview
from app.macro import service as service_module
from app.macro.service import runtime, sync, vix_regime
from app.market import settlement_epoch
from app.settings import save_settings
from tests.macro.conftest import FakeProvider, observation, seed, unit

DAY = date(2026, 11, 20)
TS = settlement_epoch(DAY)
NEXT_DAY = date(2026, 11, 19)
NEXT_TS = settlement_epoch(NEXT_DAY)


def _count(series_id: str, ts: int, provider: str) -> int:
    with session_scope() as session:
        return session.execute(
            text(
                "select count(*) from macro_observations "
                "where series_id = :series and ts = :ts and provider = :provider"
            ),
            {"series": series_id, "ts": ts, "provider": provider},
        ).scalar_one()


def _total() -> int:
    with session_scope() as session:
        return session.execute(text("select count(*) from macro_observations")).scalar_one()


def _us10y_minute(overview=None):
    data = overview or macro_overview()
    return next(
        item for item in data.readings if item.series_id == "us10y" and item.granularity == "minute"
    )


def test_sync_upsert_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一 `(series_id, ts, provider)` 抓三次只有一行（AC2）。"""

    fake = FakeProvider(
        "yahoo",
        {"us10y": [observation("us10y", ts=TS, value="4.92", provider="yahoo", is_delayed=True)]},
    )
    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: fake)
    target = unit("us10y", "minute", "yahoo")

    for _ in range(3):
        results = sync(units=[target])
        assert results[0].status == "synced"
        assert results[0].rows == 1

    assert _count("us10y", TS, "yahoo") == 1
    assert _total() == 1


def test_switching_provider_uses_new_implementation(monkeypatch: pytest.MonkeyPatch) -> None:
    """`vix.minute` 从 yahoo 换成 cboe 后下一次 tick 走新实现（AC1）。"""

    seen: list[str] = []

    def builder(name: str, **_: object) -> FakeProvider:
        seen.append(name)
        return FakeProvider(
            name,
            {
                "vix": [
                    observation(
                        "vix", ts=TS, value="35.89", provider=name, is_delayed=name == "yahoo"
                    )
                ]
            },
        )

    monkeypatch.setattr(service_module, "build_provider", builder)
    save_settings(data_sources={"macro": {"series": {"vix": {"minute": "cboe"}}}})

    results = sync(units=[unit("vix", "minute", "cboe")])

    assert results[0].status == "synced"
    assert seen == ["cboe"]
    reading = next(
        item
        for item in macro_overview().readings
        if item.series_id == "vix" and item.granularity == "minute"
    )
    assert reading.provider == "cboe"
    assert reading.value == Decimal("35.89")


def test_overview_never_calls_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    """总览只读库：上游不可用期间调用计数恒为 0（AC6）。"""

    seed("us10y", ts=TS, value="4.92", provider="yahoo", trading_day=DAY, is_delayed=True)

    def boom(name: str, **_: object) -> object:
        raise AssertionError(f"总览不得请求上游: {name}")

    monkeypatch.setattr(service_module, "build_provider", boom)

    overview = macro_overview()

    assert _us10y_minute(overview).value == Decimal("4.92")


def test_overview_degrades_to_cached_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游失败时返回缓存值 + `stale`，数值一字不变，不填假数据（AC8）。"""

    seed("us10y", ts=TS, value="4.92", provider="yahoo", trading_day=DAY, is_delayed=True)
    before = _us10y_minute()

    class Failing:
        name = "yahoo"

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series: object, since: object) -> list[object]:
            raise UpstreamError("宏观数据上游请求失败: 断网")

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: Failing())

    results = sync(units=[unit("us10y", "minute", "yahoo")])

    assert results[0].status == "failed"
    after = _us10y_minute()
    assert after.value == before.value
    assert after.as_of == before.as_of
    assert macro_overview().stale is True
    assert "断网" in (macro_overview().stale_reason or "")


def test_sync_skips_unit_that_is_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider("yahoo", {"us10y": []})
    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: fake)
    target = unit("us10y", "minute", "yahoo")

    assert runtime().acquire(target) is True
    try:
        results = sync(units=[target])
    finally:
        runtime().release(target)

    assert results[0].status == "skipped"
    assert fake.calls == []


def test_backoff_window_expires_and_probe_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """连续失败会退避并标记 degraded，但退避结束后仍要放行试探抓取。

    `degraded` 只用于健康展示：若它也能拦住抓取，清空它的成功路径就永远走不到，单元会
    永久停摆、总览永久 stale。
    """

    moment = [datetime(2026, 11, 22, 7, 0, tzinfo=UTC)]
    state = {"fail": True, "calls": 0}

    class Clock:
        def now(self) -> datetime:
            return moment[0]

    class Toggle:
        name = "yahoo"

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series: object, since: object) -> list[object]:
            state["calls"] += 1
            if state["fail"]:
                raise UpstreamError("上游 503")
            return [observation("us10y", ts=TS, value="4.92", provider="yahoo", is_delayed=True)]

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: Toggle())
    target = unit("us10y", "minute", "yahoo")

    def tick() -> str:
        return sync(units=[target], clock=Clock(), respect_backoff=True)[0].status

    assert tick() == "failed"
    assert runtime().status()["series"][0]["failures"] == 1

    moment[0] += timedelta(seconds=30)  # 1× 退避窗口内：跳过，不打上游
    assert tick() == "skipped"
    assert state["calls"] == 1

    moment[0] += timedelta(seconds=61)  # 窗口结束：放行一次试探
    assert tick() == "failed"
    moment[0] += timedelta(seconds=121)  # 2× 窗口结束
    assert tick() == "failed"

    status = runtime().status()
    assert status["degraded"] is True
    assert status["series"][0]["failures"] == 3
    assert state["calls"] == 3

    # 关键：degraded 不拦住下一次试探；成功后退避与错误一起清零。
    state["fail"] = False
    moment[0] += timedelta(seconds=241)  # 4× 窗口结束
    assert tick() == "synced"

    status = runtime().status()
    assert status["degraded"] is False
    assert status["last_error"] is None
    assert status["series"][0]["failures"] == 0
    assert macro_overview().stale is False


def test_historical_settlement_rows_sync_on_a_fresh_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """日更源的历史可以回溯几十年；首次同步不能因为休市日表缺年份就整份失败（QA D1）。"""

    old_day = date(1990, 1, 2)
    old_ts = settlement_epoch(old_day)
    fake = FakeProvider(
        "cboe",
        {"vix": [observation("vix", ts=old_ts, value="17.24", provider="cboe")]},
    )
    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: fake)

    results = sync(units=[unit("vix", "daily", "cboe")])

    assert results[0].status == "synced", results[0].error
    assert results[0].rows == 1
    assert _count("vix", old_ts, "cboe") == 1


def test_write_failure_is_reported_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """落库失败必须记成 failed，不能因为管道吞异常就回报 synced。"""

    fake = FakeProvider(
        "yahoo",
        {"us10y": [observation("us10y", ts=TS, value="4.92", provider="yahoo", is_delayed=True)]},
    )
    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: fake)

    def boom(records: object, *, now: object = None) -> int:
        raise RuntimeError("数据库断连")

    monkeypatch.setattr("app.macro.pipeline.save_observations", boom)

    results = sync(units=[unit("us10y", "minute", "yahoo")])

    assert results[0].status == "failed"
    assert "落库失败" in (results[0].error or "")
    assert results[0].rows == 0
    status = runtime().status()
    assert "数据库断连" in (status["last_error"] or "")
    assert _total() == 0


def test_source_url_follows_each_rows_provider() -> None:
    """同一序列的分钟级与日结值来自不同上游，来源地址必须各自指向自己的 provider。"""

    seed("us10y", ts=TS, value="4.92", provider="treasury", trading_day=DAY)
    seed("us10y", ts=TS + 3600, value="4.91", provider="yahoo", trading_day=DAY, is_delayed=True)

    readings = {
        item.granularity: item for item in macro_overview().readings if item.series_id == "us10y"
    }

    assert readings["daily"].source_url is not None
    assert "treasury.gov" in readings["daily"].source_url
    assert readings["minute"].source_url is not None
    assert "yahoo" in readings["minute"].source_url


def test_spread_uses_same_settlement_day() -> None:
    seed("us10y", ts=TS, value="4.92", provider="treasury", trading_day=DAY)
    seed("us2y", ts=TS, value="4.63", provider="treasury", trading_day=DAY)

    spread = macro_overview().spread

    assert spread.available is True
    assert spread.value_bp == Decimal("29")
    assert spread.inverted is False
    assert spread.trading_day == DAY


def test_spread_carries_the_pairing_source() -> None:
    """AC3：利差行同样要有来源；默认配置下 2Y 与 10Y 都来自财政部，合成一条。"""

    seed("us10y", ts=TS, value="4.92", provider="treasury", trading_day=DAY)
    seed("us2y", ts=TS, value="4.63", provider="treasury", trading_day=DAY)

    spread = macro_overview().spread

    assert [source.provider for source in spread.sources] == ["treasury"]
    assert spread.sources[0].source_url is not None
    assert "treasury.gov" in spread.sources[0].source_url


def test_spread_refuses_a_leg_that_is_not_a_settlement_value() -> None:
    """防线：即使库里/配置里混进了非结算值，也不用它计算利差。

    横轴上多一小时的那条不是日结值（时刻不等于收盘），必须判不可用，而不是凑出一个
    「看起来正常」的差值。
    """

    seed("us10y", ts=TS + 3600, value="4.92", provider="treasury", trading_day=DAY)
    seed("us2y", ts=TS, value="4.63", provider="treasury", trading_day=DAY)

    spread = macro_overview().spread

    assert spread.available is False
    assert spread.value_bp is None
    assert "不是日结值" in (spread.reason or "")
    assert [source.provider for source in spread.sources] == ["treasury"]


def test_spread_is_unavailable_when_settlement_days_differ() -> None:
    seed("us10y", ts=TS, value="4.92", provider="treasury", trading_day=DAY)
    seed("us2y", ts=NEXT_TS, value="4.63", provider="treasury", trading_day=NEXT_DAY)

    spread = macro_overview().spread

    assert spread.available is False
    assert spread.value_bp is None
    assert "结算日" in (spread.reason or "")


def test_spread_is_unavailable_without_two_year() -> None:
    seed("us10y", ts=TS, value="4.92", provider="treasury", trading_day=DAY)

    spread = macro_overview().spread

    assert spread.available is False
    assert "2Y" in (spread.reason or "")


def test_inverted_spread_is_flagged() -> None:
    seed("us10y", ts=TS, value="4.10", provider="treasury", trading_day=DAY)
    seed("us2y", ts=TS, value="4.63", provider="treasury", trading_day=DAY)

    spread = macro_overview().spread

    assert spread.available is True
    assert spread.inverted is True
    assert spread.value_bp == Decimal("-53")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("14.99", "low"),
        ("15", "normal"),
        ("19.99", "normal"),
        ("20", "elevated"),
        ("30", "elevated"),
        ("30.01", "panic"),
        ("35.89", "panic"),
    ],
)
def test_vix_regime_thresholds(value: str, expected: str) -> None:
    assert vix_regime(Decimal(value)) == expected
