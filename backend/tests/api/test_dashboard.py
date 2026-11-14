"""首页聚合端点：八个模块齐全、独立降级、只读与各模块时刻。

数据全部走业务写入路径（标的同步、日线落库、手动持仓、策略实例、回测、风险事件），
不手写响应形状。断言只针对可以从库与请求复算出来的值：

- 任何模块异常都只把自己标成 `unavailable`，响应仍是 200；
- 账户未配置只降级 `account`，其他模块继续返回；
- 提醒只给未处置事件，自选只给摘要，策略没有回测时 `recent_backtest` 为 `null`；
- 一次请求不写任何业务表。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.core import Bar, Timeframe
from app.db.engine import get_engine
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.risk import RiskContext, RiskEngine, TradeRequest, resolve_risk_event
from app.strategy import create_instance
from tests.api.conftest import latest_opens, seed_daily
from tests.factories.instruments import make_ref, make_swap_ref

D = Decimal
DAY = timedelta(days=1)
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
MODULES = (
    "market",
    "account",
    "risk",
    "positions",
    "watchlist",
    "alerts",
    "strategies",
    "activity",
)
TRACKED_TABLES = (
    "instruments",
    "candles",
    "watchlist_items",
    "manual_positions",
    "strategy_instances",
    "backtest_runs",
    "risk_events",
    "account_snapshots",
)


def _swap_market() -> None:
    """一现货一永续、各三根日线；两类标的都有可读行情。"""

    sync_instruments([make_ref(), make_swap_ref()])
    seed_daily("XAAPL-USDT", ["100", "110", "121"])
    seed_daily("AAPL-USDT-SWAP", ["50", "55", "60.5"])


def _strategy_market() -> None:
    """两只加密现货，各六根日线，供策略回测使用。"""

    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    opens = [AS_OF - DAY * (5 - index) for index in range(6)]
    for inst_id, closes in (
        ("BTC-USDT", ["100", "101", "102", "103", "104", "105"]),
        ("ETH-USDT", ["50", "51", "52", "53", "55", "58"]),
    ):
        upsert_candles(
            [
                Bar(
                    inst_id=inst_id,
                    timeframe=Timeframe.parse("1d"),
                    open_time=open_time,
                    open=D(close),
                    high=D(close),
                    low=D(close),
                    close=D(close),
                    volume=D("10"),
                    confirm=True,
                    source="okx_spot",
                )
                for open_time, close in zip(opens, closes, strict=True)
            ]
        )


def _spot_market(symbols: list[str], closes: list[str]) -> None:
    """一批加密现货写同一段日线；现货来源固定是 `okx_spot`，不受美股时段影响。"""

    sync_instruments(
        [
            make_ref(inst_id=f"{symbol}-USDT", base_ccy=symbol, inst_category="1")
            for symbol in symbols
        ]
    )
    opens = latest_opens(len(closes))
    for symbol in symbols:
        upsert_candles(
            [
                Bar(
                    inst_id=f"{symbol}-USDT",
                    timeframe=Timeframe.parse("1d"),
                    open_time=open_time,
                    open=D(close),
                    high=D(close),
                    low=D(close),
                    close=D(close),
                    volume=D("10"),
                    confirm=True,
                    source="okx_spot",
                )
                for open_time, close in zip(opens, closes, strict=True)
            ]
        )


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()


@pytest.fixture()
def unconfigured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """没有 OKX 凭据的进程配置；退出时恢复缓存，避免影响其他用例。"""

    _clear_credentials(monkeypatch)
    yield
    get_settings.cache_clear()


def _table_snapshot() -> dict[str, tuple[int, str]]:
    """每张关键表的行数与整表内容摘要；用来证明一次请求不写库。"""

    engine = get_engine()
    snapshot: dict[str, tuple[int, str]] = {}
    with engine.connect() as connection:
        for table in TRACKED_TABLES:
            exists = connection.execute(text("SELECT to_regclass(:name)"), {"name": table}).scalar()
            if exists is None:
                snapshot[table] = (0, "")
                continue
            statement = (
                "SELECT count(*), "
                "coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '') "
                f'FROM "{table}" t'
            )
            count, digest = connection.execute(text(statement)).one()
            snapshot[table] = (int(count), str(digest))
    return snapshot


def test_empty_database_returns_all_eight_modules(client: TestClient) -> None:
    """空库也能返回八个模块：不可计算的值留空，不补造数字。"""

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {*MODULES, "as_of", "degraded"}
    for name in MODULES:
        module = body[name]
        assert set(module) == {"status", "as_of", "error", "data"}

    assert body["account"]["status"] == "unconfigured"
    assert body["account"]["data"] is None
    assert body["account"]["error"] == "账户未配置"
    assert body["positions"]["status"] == "ok"
    assert body["positions"]["data"] == {
        "total": 0,
        "exchange_count": 0,
        "manual_count": 0,
        "exchange_status": "unconfigured",
        "items": [],
    }
    assert body["risk"]["status"] == "ok"
    assert body["alerts"]["data"] == []
    assert body["activity"]["data"] == []
    assert body["watchlist"]["data"] == {
        "summary": {"total": 0, "bullish": 0, "bearish": 0, "coverage_pct": "0"},
        "items": [],
    }
    assert body["strategies"]["data"]["recent_backtest"] is None
    assert body["degraded"] == [
        {
            "module": "account",
            "status": "unconfigured",
            "reason": "账户未配置",
            "last_success_at": None,
        }
    ]


def test_populated_dashboard_aggregates_each_domain(client: TestClient) -> None:
    """持仓、自选与风险各写一条真实数据，首页按域汇总。"""

    _swap_market()
    created = client.post(
        "/api/manual-positions",
        json={
            "inst_id": "AAPL-USDT-SWAP",
            "side": "long",
            "quantity": "2",
            "avg_cost": "55",
            "stop_px": "58",
            "leverage": "2",
            "idempotency_key": "dashboard-1",
        },
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]
    assert client.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"}).status_code == 201

    body = client.get("/api/dashboard/summary").json()

    positions = body["positions"]["data"]
    assert positions["total"] == 1
    assert positions["manual_count"] == 1
    assert positions["items"][0]["position_ref"] == f"manual:{position_id}"
    assert positions["items"][0]["source"] == "manual"
    assert positions["items"][0]["display_symbol"] == "AAPL-USDT"
    assert D(positions["items"][0]["notional"]) == D("2") * D("60.5")
    assert D(positions["items"][0]["stop_distance_pct"]) == (
        (D("60.5") - D("58")) / D("60.5") * D("100")
    ).quantize(D("0.000000000001"))

    watchlist = body["watchlist"]["data"]
    assert watchlist["summary"] == {
        "total": 1,
        "bullish": 0,
        "bearish": 0,
        "coverage_pct": "100",
    }
    assert watchlist["items"][0]["inst_id"] == "XAAPL-USDT"
    assert watchlist["items"][0]["display_symbol"] == "AAPL-USDT"
    assert watchlist["items"][0]["name"] == "AAPL"
    assert D(watchlist["items"][0]["last_price"]) == D("121")
    assert watchlist["items"][0]["trend"] is None
    last_open = latest_opens(3)[-1]
    assert body["watchlist"]["as_of"] == last_open.strftime("%Y-%m-%dT%H:%M:%SZ")

    risk = body["risk"]["data"]
    assert D(risk["gross_notional"]) == D("2") * D("60.5")
    assert risk["position_count"] == 1
    assert risk["missing_stop_count"] == 0
    assert D(risk["max_single_instrument_weight_pct"]) == D("100")


def test_alerts_only_return_unresolved_events(client: TestClient) -> None:
    """提醒只给未处置事件；已处置事件不出现在首页。"""

    _swap_market()
    rejected = RiskEngine().authorize(
        TradeRequest(
            instance_id="si_dashboard",
            inst_id="XAAPL-USDT",
            side="buy",
            order_type="limit",
            qty=D("100"),
            price=D("100"),
            ts=AS_OF,
        ),
        RiskContext(equity=D("10000"), available_balance=D("10000")),
    )
    assert not rejected.allowed

    first = client.get("/api/dashboard/summary").json()["alerts"]
    assert first["status"] == "ok"
    assert len(first["data"]) == len(rejected.violations) > 0
    assert {item["type"] for item in first["data"]} == {"risk"}
    assert {item["status"] for item in first["data"]} == {"pending"}
    assert {item["rule_id"] for item in first["data"]} == {
        item.rule for item in rejected.violations
    }
    assert first["as_of"] == "2026-11-10T23:00:00Z"

    event_ids = [item["event_id"] for item in client.get("/api/risk/events").json()["items"]]
    assert len(event_ids) == len(rejected.violations)
    assert resolve_risk_event(event_ids[0], at=AS_OF) is not None

    second = client.get("/api/dashboard/summary").json()["alerts"]
    assert len(second["data"]) == len(first["data"]) - 1
    assert event_ids[0] not in {item["id"] for item in second["data"]}


def test_strategies_count_and_recent_backtest(client: TestClient) -> None:
    """策略卡给出实例计数与最近 30 天的一次回测；没有回测时为 `null`。"""

    _strategy_market()
    instance = create_instance(
        strategy_id="relative_value",
        name="BTC/ETH 首页",
        bar="1d",
        params={"reversion_window": 3, "strength_window": 2, "pair_count": 1},
        inst_ids=["BTC-USDT", "ETH-USDT"],
    )

    before = client.get("/api/dashboard/summary").json()["strategies"]["data"]
    assert before == {
        "total": 1,
        "enabled": 1,
        "running": 0,
        "pending_signals": None,
        "recent_backtest": None,
    }

    run = client.post(
        "/api/backtests",
        json={
            "strategy_instance_id": instance.instance_id,
            "targets": {"mode": "single", "inst_ids": ["BTC-USDT"], "group": None},
            "bar": "1d",
            "start_date": "2026-11-05",
            "end_date": "2026-11-10",
            "initial_capital": "10000",
            "quote_currency": "USDT",
            "position_size": "10000",
            "max_position_pct": "1",
            "costs": {
                "maker_fee_bps": "2",
                "taker_fee_bps": "10",
                "slippage_bps": "5",
                "spread_bps": "2",
            },
            "funding_enabled": True,
            "execution_model": "next_open",
            "data_source": "okx_spot",
        },
    )
    assert run.status_code == 202, run.text

    after = client.get("/api/dashboard/summary").json()["strategies"]["data"]
    assert after["total"] == 1
    recent = after["recent_backtest"]
    assert recent is not None
    assert recent["run_id"] == run.json()["run_id"]
    assert recent["data_source"] == "okx_spot"
    assert recent["window_days"] == 5
    assert recent["trade_count"] == run.json()["metrics"]["trade_count"]
    assert D(recent["total_return"]) == D(run.json()["metrics"]["total_return_pct"]) / D("100")
    assert D(recent["max_drawdown"]) == D(run.json()["metrics"]["max_drawdown_pct"]) / D("100")


def test_account_unconfigured_only_degrades_its_own_module(
    client: TestClient,
    unconfigured: None,
) -> None:
    """断开账户配置只降级 `account`，其余七个模块仍为 `ok`。"""

    _swap_market()
    client.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    body = client.get("/api/dashboard/summary").json()

    assert body["account"]["status"] == "unconfigured"
    assert body["account"]["data"] is None
    assert body["account"]["error"] == "账户未配置"
    for name in ("market", "risk", "positions", "watchlist", "alerts", "strategies", "activity"):
        assert body[name]["status"] == "ok", name
    assert [item["module"] for item in body["degraded"]] == ["account"]


def test_module_failure_is_isolated(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自选读取抛错只把该模块标成不可用，响应仍是 200，其他模块照常返回。"""

    from app.dashboard import service as dashboard_service

    _swap_market()

    def boom() -> object:
        raise RuntimeError("自选读取失败")

    monkeypatch.setattr(dashboard_service, "list_entries", boom)

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["watchlist"] == {
        "status": "unavailable",
        "as_of": None,
        "error": "数据读取失败",
        "data": None,
    }
    for name in ("market", "risk", "positions", "strategies", "activity"):
        assert body[name]["status"] == "ok", name
    assert body["degraded"] == [
        {
            "module": "account",
            "status": "unconfigured",
            "reason": "账户未配置",
            "last_success_at": None,
        },
        {
            "module": "watchlist",
            "status": "unavailable",
            "reason": "数据读取失败",
            "last_success_at": None,
        },
    ]
    assert "自选读取失败" not in response.text


def test_dashboard_request_does_not_write(client: TestClient) -> None:
    """一次请求只读：关键业务表的行数与整表摘要都不变。"""

    _swap_market()
    client.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})
    before = _table_snapshot()

    assert client.get("/api/dashboard/summary").status_code == 200

    assert _table_snapshot() == before


def test_market_breadth_and_resonance_render_numbers(client: TestClient) -> None:
    """广度比值与共振强度非空时也要能出接口，不能被格式化层拒收。"""

    _spot_market([f"C{index}" for index in range(8)], ["100", "101", "102"])
    _spot_market([f"D{index}" for index in range(2)], ["100", "99", "98"])

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    spot = next(item for item in body["market"]["data"]["items"] if item["inst_type"] == "SPOT")
    assert spot["breadth"] == {
        "advancers": 8,
        "decliners": 2,
        "unchanged": 0,
        "ratio": "4",
        "participants": 10,
    }
    assert spot["resonance"] == {"strength": "0.6", "participants": 10, "window": 20}


def test_exposure_report_is_read_once_per_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """风险与持仓共用同一份敞口结果，一次请求只读一次。"""

    from app.dashboard import service as dashboard_service

    calls: list[int] = []
    original = dashboard_service.exposure_report

    def counting() -> object:
        calls.append(1)
        return original()

    monkeypatch.setattr(dashboard_service, "exposure_report", counting)
    _swap_market()

    body = client.get("/api/dashboard/summary").json()

    assert body["risk"]["status"] == "ok"
    assert body["positions"]["status"] == "ok"
    assert len(calls) == 1
