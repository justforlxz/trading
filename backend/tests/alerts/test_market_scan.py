"""大盘异动与组合异动的落库、状态跃迁与订阅矩阵。

纯判定在 `tests/alerts/test_market_rules.py`；这里验证「跨阈值才发」这条承诺在数据库
里的表现：同一级别持续不新增，回落后再跨过重新激活同一条提醒，以及新类型出现在设置
页的订阅矩阵里。
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.alerts import (
    AlertCandidate,
    AlertEventRow,
    record_candidate,
    scan_alerts,
    scan_market_alerts,
)
from app.core import Bar, Timeframe
from app.db import session_scope
from app.market import settlement_epoch, upsert_candles
from tests.api.conftest import seed_daily, seed_instruments
from tests.factories.instruments import make_ref, make_swap_ref
from tests.macro.conftest import seed as seed_observation

#: 固定「现在」：所有日线的开盘时间都排在它之前 120 天以内。
NOW = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)
BASE = NOW - timedelta(days=100)
#: 基线波幅：ATR20 恰好是收盘价的 2.82%。
RANGE_PCT = Decimal("0.0282")


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def _bar(index: int, close: Decimal, *, symbol: str = "^SOX") -> Bar:
    half = close * RANGE_PCT / 2
    return Bar(
        inst_id=symbol,
        timeframe=Timeframe.parse("1d"),
        open_time=BASE + timedelta(days=index),
        open=close,
        high=close + half,
        low=close - half,
        close=close,
        volume=Decimal("1"),
        confirm=True,
        source="yahoo",
    )


def _seed_index(closes: list[Decimal], *, symbol: str = "^SOX") -> None:
    upsert_candles([_bar(index, close, symbol=symbol) for index, close in enumerate(closes)])


def _baseline() -> list[Decimal]:
    """21 根收平的日线：ATR20 的基线是 2.82%。"""

    return [Decimal("100")] * 21


def _alerts() -> list[AlertEventRow]:
    with session_scope() as session:
        return list(session.scalars(select(AlertEventRow).order_by(AlertEventRow.triggered_at)))


def _scan(day: int):
    return scan_market_alerts(clock=_FixedClock(BASE + timedelta(days=day)))


def test_a_level_change_creates_one_alert_per_level() -> None:
    """11.4% 的涨幅是 4 倍 ATR20，落在紧急级；提醒的标的留空，指数写进载荷。"""

    _seed_index([*_baseline(), Decimal("111.4")])

    result = _scan(21)

    assert result.created == 1
    rows = _alerts()
    assert len(rows) == 1
    assert rows[0].type == "market"
    assert rows[0].severity == "critical"
    assert rows[0].instrument_id is None
    assert rows[0].rule_id == "market_sox_change"
    assert rows[0].status == "pending"
    assert "费城半导体" in rows[0].detail


def _seed_us10y(day: int, value: str, previous: str) -> None:
    """给 10Y 落两个交易日的结算值：`previous` 是前一交易日，`value` 是当天。

    收益率规则用固定基点门槛（10/20/30bp），不像 ATR 那样随波动自适应，因此「连续三天
    处于紧急级」可以用它稳定构造出来。
    """

    for offset, close in ((-1, previous), (0, value)):
        moment = BASE + timedelta(days=day + offset)
        seed_observation(
            "us10y",
            ts=settlement_epoch(moment.date()),
            value=close,
            provider="treasury",
            trading_day=moment.date(),
        )


def _us10y_alerts() -> list[AlertEventRow]:
    return [row for row in _alerts() if row.rule_id == "market_us10y_bp"]


def test_three_days_at_the_same_level_send_only_once() -> None:
    """AC6：同一指标连续 3 天处于紧急级 → 只发 1 条。"""

    _seed_us10y(21, "4.832", "4.500")  # +33.2bp → 紧急
    assert _scan(21).created == 1

    _seed_us10y(22, "5.182", "4.832")  # +35bp → 紧急，级别没变
    assert _scan(22).created == 0
    _seed_us10y(23, "5.532", "5.182")  # +35bp → 紧急
    assert _scan(23).created == 0

    rows = _us10y_alerts()
    assert len(rows) == 1
    assert rows[0].severity == "critical"
    assert rows[0].status == "pending"


def test_falling_a_level_and_crossing_back_sends_again() -> None:
    """AC6：回落到提示级 1 天后再回紧急 → 再发 1 条。

    回落本身也是一次「进入该级别」，因此提示级那一条会先发出来；紧急级那条在回落时
    被标成 expired，再次跨过时用同一个键重新激活。
    """

    _seed_us10y(21, "4.832", "4.500")  # +33.2bp → 紧急
    assert _scan(21).created == 1

    _seed_us10y(22, "4.952", "4.832")  # +12bp → 提示级
    assert _scan(22).created == 1
    assert {row.severity: row.status for row in _us10y_alerts()} == {
        "critical": "expired",
        "info": "pending",
    }

    _seed_us10y(23, "5.302", "4.952")  # +35bp → 回到紧急级
    assert _scan(23).created == 1

    rows = _us10y_alerts()
    assert len(rows) == 2
    critical = next(row for row in rows if row.severity == "critical")
    assert critical.status == "pending"
    assert critical.expires_at is None


def test_falling_back_inside_the_bands_expires_the_alert() -> None:
    """回落到所有阈值以内时提醒标为过期，下一次跨过重新发。"""

    _seed_us10y(21, "4.832", "4.500")  # +33.2bp → 紧急
    assert _scan(21).created == 1

    _seed_us10y(22, "4.842", "4.832")  # +1bp：没有任何级别成立
    assert _scan(22).created == 0
    assert [row.status for row in _us10y_alerts()] == ["expired"]

    _seed_us10y(23, "5.192", "4.842")  # +35bp → 重新跨过紧急级
    assert _scan(23).created == 1
    assert [row.status for row in _us10y_alerts()] == ["pending"]


def test_full_scan_includes_the_market_alerts() -> None:
    """接口的默认扫描也带上大盘规则：用户打开页面看到的是同一份结果。"""

    _seed_index([*_baseline(), Decimal("111.4")])

    result = scan_alerts(clock=_FixedClock(BASE + timedelta(days=21)))

    assert result.created >= 1
    assert any(row.type == "market" for row in _alerts())


def test_market_alerts_are_listed_by_type(client: TestClient) -> None:
    """`GET /api/alerts?type=market` 能按新类型筛选。"""

    _seed_index([*_baseline(), Decimal("111.4")])

    response = client.get("/api/alerts", params={"type": "market"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["type"] for item in items] == ["market"]
    assert items[0]["instrument_id"] is None
    assert items[0]["severity"] == "critical"


def test_the_subscription_matrix_offers_both_new_types(client: TestClient) -> None:
    """AC1：设置页的订阅矩阵里出现 `market` 与 `watchlist` 两个类型，并且可以勾选。"""

    subscriptions = client.get("/api/settings").json()["notifications"]["subscriptions"]
    assert {"market", "watchlist"} <= set(subscriptions["browser"]["types"])

    response = client.patch(
        "/api/settings",
        json={
            "notifications": {
                "subscriptions": {
                    "telegram": {"types": ["market", "watchlist"], "min_severity": "info"}
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    saved = response.json()["notifications"]["subscriptions"]["telegram"]
    assert saved == {"types": ["market", "watchlist"], "min_severity": "info"}


@pytest.mark.parametrize("alert_type", ["market", "watchlist"])
def test_alert_list_accepts_the_new_types(client: TestClient, alert_type: str) -> None:
    response = client.get("/api/alerts", params={"type": alert_type})

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_the_alerts_package_has_no_scheduling_primitives() -> None:
    """AC7：提醒域不新增定时器——大盘与组合异动挂在行情调度轮次上。

    这条用例是 AC7 的自动化版本：`grep -rnE "cron|schedule|interval|while True"` 在
    `backend/app/alerts` 下必须没有命中，否则说明有人在这里另起了一套轮询。
    """

    pattern = re.compile(r"cron|schedule|interval|while True")
    alerts_root = Path(__file__).resolve().parents[2] / "app" / "alerts"
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for path in sorted(alerts_root.glob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert offenders == []


def test_only_the_newest_source_feeds_the_atr_baseline() -> None:
    """换过数据源后旧来源的行还在表里；混成一条序列会算出不存在的跳空。

    以最新一根的来源为准：这一天最新的是 stooq，它只有一根日线，算不出 ATR20，
    因此不发提醒——而不是拿 yahoo 的 21 根接上去凑一个基线。
    """

    _seed_index([*_baseline(), Decimal("111.4")])
    latest = _bar(22, Decimal("500"))
    upsert_candles([replace(latest, source="stooq")])

    assert _scan(22).created == 0


def test_the_market_scan_does_not_expire_security_alerts(client: TestClient) -> None:
    """回归（评审阻断项）：只评估大盘的那一轮不能把技术/风险提醒判成「已恢复」。

    以前 `_expire_stale` 只有一个调用方，每次都带着全部规则的候选，因此「这批候选就是
    我负责的全部规则」这个前提从来没被打破；`scan_market_alerts` 一进来就把这个前提
    踩坏——实盘每个交易日收盘后至少跑一次，只要当时有待处理的风险提醒就会被清空。
    """

    seed_instruments(make_ref(), make_swap_ref())
    seed_daily("XAAPL-USDT", ["100", "110", "121"])
    seed_daily("AAPL-USDT-SWAP", ["50", "55", "60.5"])
    response = client.post(
        "/api/manual-positions",
        json={
            "inst_id": "AAPL-USDT-SWAP",
            "side": "long",
            "quantity": "2",
            "avg_cost": "55",
            "leverage": "2",
            "idempotency_key": "market-scan-regression",
        },
    )
    assert response.status_code == 201, response.text
    assert scan_alerts().created > 0
    before = {row.rule_id: row.status for row in _alerts()}
    assert before["stop_missing"] == "pending"

    # 同一时刻出现大盘异动：只评估大盘的那一轮不得触碰风险与技术的提醒。
    _seed_index([*_baseline(), Decimal("111.4")])
    _scan(21)

    after = {row.rule_id: row.status for row in _alerts()}
    assert after["stop_missing"] == "pending"
    assert after["market_sox_change"] == "pending"


def test_the_market_scan_leaves_a_pending_technical_alert_pending() -> None:
    """同样的保证对技术形态成立：不在这一轮评估范围里的规则一律不动。"""

    record_candidate(
        AlertCandidate(
            type="indicator",
            severity="info",
            instrument_id=None,
            rule_id="ma20_cross",
            rule_version="indicator-v1",
            title="收盘价跌破 MA20",
            detail="TEST-USDT 收盘价 80 跌破 MA20（100）",
            dedup_key="indicator|ma20_cross|TEST-USDT|2026-11-01T13:30:00+00:00|down",
            triggered_at=BASE,
        )
    )
    _seed_index([*_baseline(), Decimal("111.4")])

    _scan(21)

    statuses = {row.rule_id: row.status for row in _alerts()}
    assert statuses == {"ma20_cross": "pending", "market_sox_change": "pending"}
