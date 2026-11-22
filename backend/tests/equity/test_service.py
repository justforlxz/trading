"""美股渠道的抓取入口与只读总览。

覆盖三条对外承诺：改配置即换实现（AC1）、重复抓取不新增行（AC2）、上游失败降级为
缓存值 + `stale` 且不返回 500（AC3）。上游用 `tests/equity/conftest.py` 的替身，
真实解析由 `tests/exchange/test_equity_providers.py` 覆盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import UpstreamError
from app.equity import (
    equity_overview,
    reset_runtime,
    runtime,
    sync,
)
from app.equity import service as service_module
from app.market import US_EQUITY, daily_open_time, from_epoch, settlement_epoch
from app.settings import load_settings, save_settings
from tests.equity.conftest import (
    CLOSE_ET,
    LAST_MINUTE_ET,
    FakeProvider,
    candle_count,
    equity_bar,
    seed,
)

NOW = datetime(2026, 11, 20, 21, 5, tzinfo=UTC)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.fixture(autouse=True)
def _clean_runtime():
    """进程内状态是单例：用例之间必须清空，否则退避会跨用例生效。"""

    reset_runtime()
    yield
    reset_runtime()


def _provider(**kwargs) -> FakeProvider:
    return FakeProvider("yahoo", **kwargs)


def _install(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> list[tuple[str, str]]:
    """把 `build_provider` 换成替身；返回「被构造过的 (provider, bar)」记录。"""

    built: list[tuple[str, str]] = []

    def build(name: str, **_: object) -> FakeProvider:
        built.append((name, provider.bar))
        provider.name = name
        return provider

    monkeypatch.setattr(service_module, "build_provider", build)
    return built


def test_sync_writes_bars_and_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(bars=[equity_bar(open_time=LAST_MINUTE_ET)])
    _install(monkeypatch, provider)

    results = sync(clock=_FixedClock(NOW))

    assert [item.status for item in results] == ["synced"]
    assert results[0].rows == 1
    assert results[0].published == 1
    assert results[0].provider == "yahoo"
    assert candle_count(symbol="SPY") == 1
    status = runtime().status()
    assert status["last_success_at"] == "2026-11-20T21:05:00Z"
    assert status["last_error"] is None
    assert status["degraded"] is False


def test_sync_fetches_the_configured_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(bars=[])
    _install(monkeypatch, provider)

    sync(clock=_FixedClock(NOW))

    symbols, start, end = provider.calls[0]
    assert symbols == ("SPY", "QQQ")
    assert end == NOW
    # 分钟级回看一周：只回看 24 小时会在周末与周一一早把上一个交易日整段过滤掉。
    assert start == NOW - timedelta(days=7)


def test_a_weekend_run_still_ingests_the_previous_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """周日或周一早上运行时，「最近 24 小时」整段落在休市区间里。

    上游给的是最近一个交易日的分钟线，窗口必须把它包住，否则每小时都抓 0 根。
    """

    sunday_noon = datetime(2026, 11, 22, 15, 48, tzinfo=UTC)
    # 周五 2026-11-20 的最后一分钟（美东 15:59）。
    friday_last = datetime(2026, 11, 20, 20, 59, tzinfo=UTC)
    provider = _provider(bars=[equity_bar(open_time=friday_last)])
    _install(monkeypatch, provider)

    results = sync(clock=_FixedClock(sunday_noon))

    assert [item.status for item in results] == ["synced"]
    assert results[0].rows == 1
    assert candle_count(symbol="SPY") == 1


def test_three_syncs_keep_a_single_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2：同一标的同一分钟连续抓三次，`candles` 不新增行。"""

    provider = _provider(bars=[equity_bar(open_time=LAST_MINUTE_ET)])
    _install(monkeypatch, provider)

    for _ in range(3):
        assert sync(clock=_FixedClock(NOW))[0].status == "synced"

    assert candle_count(symbol="SPY") == 1


def test_switching_the_provider_uses_the_new_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1：`equity.provider` 从 yahoo 切到 stooq 后走新实现，数据仍入库。"""

    provider = _provider(bars=[equity_bar(open_time=LAST_MINUTE_ET)], bar="1m")
    built = _install(monkeypatch, provider)

    sync(clock=_FixedClock(NOW))
    assert built == [("yahoo", "1m")]

    # 只改配置：调用方代码不动。
    save_settings(data_sources={"equity": {"provider": "stooq"}})
    provider.bar = "1d"
    provider.bars = [equity_bar(open_time=CLOSE_ET, bar="1d", source="stooq")]
    results = sync(clock=_FixedClock(NOW))

    assert built == [("yahoo", "1m"), ("stooq", "1d")]
    assert results[0].provider == "stooq"
    assert results[0].bar == "1d"
    assert candle_count(symbol="SPY") == 2  # 两个来源各一行，互不覆盖
    assert load_settings().data_sources["equity"]["provider"] == "stooq"


def test_sync_records_a_failure_and_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(error=UpstreamError("连接被拒绝"))
    _install(monkeypatch, provider)

    failed = sync(clock=_FixedClock(NOW))
    assert [item.status for item in failed] == ["failed"]
    assert "连接被拒绝" in (failed[0].error or "")
    status = runtime().status()
    assert status["failures"] == 1
    assert status["last_error"] == "连接被拒绝"
    assert status["last_success_at"] is None

    # 退避窗口内调度器不再打上游；手动触发（不尊重退避）仍然重试。
    provider.error = None
    provider.bars = [equity_bar(open_time=LAST_MINUTE_ET)]
    assert sync(respect_backoff=True, clock=_FixedClock(NOW))[0].status == "skipped"
    assert sync(clock=_FixedClock(NOW))[0].status == "synced"
    assert runtime().status()["failures"] == 0


def test_a_foreign_source_in_the_batch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider 只能交出来自它自己的行，否则来源就不可信。"""

    provider = _provider(bars=[equity_bar(open_time=LAST_MINUTE_ET)])
    _install(monkeypatch, provider)

    original = provider.fetch

    def fetch(symbols, start, end):
        return [equity_bar(open_time=LAST_MINUTE_ET, source="okx")]

    provider.fetch = fetch  # type: ignore[method-assign]

    results = sync(clock=_FixedClock(NOW))

    assert [item.status for item in results] == ["failed"]
    assert "别的来源" in (results[0].error or "")
    assert candle_count(symbol="SPY") == 0
    provider.fetch = original  # type: ignore[method-assign]


def test_concurrent_tick_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(bars=[])
    _install(monkeypatch, provider)
    assert runtime().acquire() is True

    try:
        results = sync(clock=_FixedClock(NOW))
    finally:
        runtime().release()

    assert [item.status for item in results] == ["skipped"]
    assert provider.calls == []


def test_overview_reads_the_latest_closed_bar() -> None:
    seed(equity_bar(open_time=LAST_MINUTE_ET, close="689.81", market_session="regular"))

    overview = equity_overview(clock=_FixedClock(NOW))

    assert [item.symbol for item in overview.readings] == ["SPY", "QQQ"]
    reading = overview.readings[0]
    assert reading.value == Decimal("689.81")
    # `as_of` 是这根 K 线的收盘时刻，不是开盘时刻。
    assert reading.as_of == LAST_MINUTE_ET + timedelta(minutes=1)
    assert reading.market_session == "regular"
    assert reading.is_delayed is True
    assert reading.quality_status == "delayed"
    assert reading.provider == "yahoo"
    # 来源链接按标的替换占位符：首页点开不能是一个带花括号的无效地址。
    assert reading.source_url is not None
    assert "{symbol}" not in reading.source_url
    assert "SPY" in reading.source_url
    # QQQ 没有数据：如实标缺失，顶层给出原因。
    assert overview.readings[1].quality_status == "missing"
    assert overview.stale is True
    assert "QQQ" in (overview.stale_reason or "")


def test_overview_marks_cached_values_stale_when_the_upstream_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3：上游失败时返回缓存值，但必须标 `stale` 并带出失败原因。

    只标「缺数据」和「数据超过 3 天」是不够的：上游停摆时库里的新鲜缓存值也不是当前
    可用数据（功能检测 01a2043f 的失败项）。
    """

    seed(
        equity_bar(open_time=LAST_MINUTE_ET, close="689.81", market_session="regular"),
        equity_bar(
            symbol="QQQ", open_time=LAST_MINUTE_ET, close="608.45", market_session="regular"
        ),
    )
    provider = _provider(error=UpstreamError("连接被拒绝"))
    _install(monkeypatch, provider)
    assert sync(clock=_FixedClock(NOW))[0].status == "failed"

    overview = equity_overview(clock=_FixedClock(NOW))

    assert overview.stale is True
    assert "美股行情抓取失败" in (overview.stale_reason or "")
    assert "连接被拒绝" in (overview.stale_reason or "")
    # 缓存值照常返回，只是标成过期：数值不丢、不返回 500。
    assert [item.value for item in overview.readings] == [
        Decimal("689.81"),
        Decimal("608.45"),
    ]
    assert {item.quality_status for item in overview.readings} == {"stale"}


def test_a_successful_sync_clears_the_stale_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    seed(equity_bar(open_time=LAST_MINUTE_ET, market_session="regular"))
    provider = _provider(error=UpstreamError("连接被拒绝"))
    _install(monkeypatch, provider)
    assert sync(clock=_FixedClock(NOW))[0].status == "failed"
    assert equity_overview(clock=_FixedClock(NOW)).stale is True

    provider.error = None
    provider.bars = [equity_bar(open_time=LAST_MINUTE_ET)]
    assert sync(clock=_FixedClock(NOW))[0].status == "synced"

    overview = equity_overview(clock=_FixedClock(NOW))

    # QQQ 仍然缺数据，所以顶层还是 stale，但 SPY 已恢复为「延迟」而不是「过期」。
    assert overview.readings[0].quality_status == "delayed"
    assert overview.readings[0].value == Decimal("689.81")


def test_overview_marks_an_old_bar_stale() -> None:
    old = NOW - timedelta(days=5)
    seed(equity_bar(symbol="SPY", open_time=old), equity_bar(symbol="QQQ", open_time=old))

    overview = equity_overview(clock=_FixedClock(NOW))

    assert {item.quality_status for item in overview.readings} == {"stale"}
    assert overview.stale is True
    assert "未更新" in (overview.stale_reason or "")


def test_overview_degrades_when_the_database_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """断网/读库失败时返回缓存值与 `stale`，绝不 500。"""

    def broken(*_: object, **__: object) -> dict[str, object]:
        raise RuntimeError("数据库不可用")

    monkeypatch.setattr(service_module, "latest_bars", broken)

    overview = equity_overview(clock=_FixedClock(NOW))

    assert overview.stale is True
    assert "数据库不可用" in (overview.stale_reason or "")
    assert all(item.value is None for item in overview.readings)
    assert all(item.quality_status == "missing" for item in overview.readings)


def test_overview_ignores_another_source_rows() -> None:
    """换过 provider 后旧来源的行还在表里，不能被读成当前值。"""

    seed(equity_bar(open_time=LAST_MINUTE_ET, source="stooq"))

    overview = equity_overview(clock=_FixedClock(NOW))

    assert all(item.value is None for item in overview.readings)


def test_overview_uses_the_current_session_when_data_is_missing() -> None:
    overview = equity_overview(clock=_FixedClock(datetime(2026, 11, 21, 3, 0, tzinfo=UTC)))

    assert all(item.market_session == "closed" for item in overview.readings)


def test_overview_uses_the_settlement_time_for_daily_bars() -> None:
    """日线的「数据时间」是该交易日 16:00 美东收盘，不是「开盘 + 24 小时」的次日 09:30。

    阻断问题（评审 01a2040b）：按 86400 秒推算会把收盘后拿到的日线标成未来的时刻。
    """

    save_settings(data_sources={"equity": {"provider": "stooq"}})
    trading_day = date(2026, 11, 19)
    seed(
        equity_bar(
            open_time=daily_open_time(US_EQUITY, datetime(2026, 11, 19, 16, 0, tzinfo=UTC)),
            bar="1d",
            source="stooq",
            market_session="closed",
        )
    )

    overview = equity_overview(clock=_FixedClock(NOW))

    reading = overview.readings[0]
    assert reading.bar == "1d"
    assert reading.as_of == from_epoch(settlement_epoch(trading_day))
    assert reading.as_of == datetime(2026, 11, 19, 21, 0, tzinfo=UTC)
    # 定稿时刻不晚于「现在」，不会出现未来时间。
    assert reading.as_of < NOW


def test_a_repeated_sync_publishes_nothing_new(monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口覆盖整个交易日，第二次抓到的绝大多数是同一根：只有新写入的才发事件。"""

    provider = _provider(bars=[equity_bar(open_time=LAST_MINUTE_ET)])
    _install(monkeypatch, provider)

    first = sync(clock=_FixedClock(NOW))[0]
    second = sync(clock=_FixedClock(NOW))[0]

    assert (first.rows, first.published) == (1, 1)
    assert (second.rows, second.published) == (1, 0)
