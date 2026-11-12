"""概览聚合：五个区块读取既有节点产出，空数据可读，且接口只读。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import session_scope
from app.db.engine import get_engine
from app.opportunity import detect_opportunities
from app.portfolio import record_allocation, record_fill
from app.risk import RiskContext, RiskEngine, TradeRequest
from app.risk.model import RiskEventRow
from tests.factories.instruments import make_ref, make_swap_ref
from tests.opportunity.conftest import seed_daily, seed_instruments

AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)

# 每类 5 个加密资产：跨越共振所需的最少参与标的数；加密资产全天候读 OKX 行情，
# 用例因此不依赖美股休市日。
SPOT_SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
SWAP_SYMBOLS = (
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "XRP-USDT-SWAP",
    "DOGE-USDT-SWAP",
)

# 只读断言覆盖的关键表：行数与 updated_at（没有该列的表只比行数）。
READ_ONLY_TABLES = (
    "instruments",
    "candles",
    "strategy_instances",
    "virtual_positions",
    "virtual_fills",
    "allocations",
    "opportunities",
    "risk_events",
    "portfolio_adjustments",
)
UPDATED_AT_TABLES = frozenset({"candles", "strategy_instances", "virtual_positions", "allocations"})


def _seed_market() -> None:
    """两类各 5 个加密资产，各两根上涨日线；随后跑一次市场驱动机会检测。"""

    seed_instruments(
        *[
            make_ref(inst_id=symbol, base_ccy=symbol.removesuffix("-USDT"), inst_category="1")
            for symbol in SPOT_SYMBOLS
        ],
        *[
            make_swap_ref(
                inst_id=symbol,
                base_ccy="",
                ct_val_ccy=symbol.removesuffix("-USDT-SWAP"),
                inst_category="1",
            )
            for symbol in SWAP_SYMBOLS
        ],
    )
    for symbol in SPOT_SYMBOLS:
        seed_daily(symbol, ["100", "110"], inst_type="SPOT")
    for symbol in SWAP_SYMBOLS:
        seed_daily(symbol, ["50", "55"], inst_type="SWAP")
    detect_opportunities(AS_OF, "1d")


def _seed_portfolio(client: TestClient) -> str:
    """通过业务写入路径准备一个策略、资金预算与一笔虚拟成交。"""

    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "驾驶舱组合",
            "bar": "1h",
            "params": {},
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    )
    assert created.status_code == 201, created.text
    instance_id = created.json()["instance_id"]
    record_allocation(instance_id, capital_budget=Decimal("1000"), priority=1)
    record_fill(
        instance_id,
        inst_id="BTC-USDT",
        side="buy",
        qty=Decimal("2"),
        price=Decimal("100"),
        at=AS_OF,
    )
    return instance_id


def _seed_risk_event(instance_id: str) -> None:
    """用风控入口制造一条真实拒绝事件，而不是手写响应形状。"""

    engine = RiskEngine()
    result = engine.authorize(
        TradeRequest(
            instance_id=instance_id,
            inst_id="BTC-USDT",
            side="buy",
            order_type="limit",
            qty=Decimal("100"),
            price=Decimal("100"),
            ts=AS_OF,
        ),
        RiskContext(equity=Decimal("10000"), available_balance=Decimal("10000")),
    )
    assert not result.allowed


def _table_snapshot() -> dict[str, tuple[int, object]]:
    engine = get_engine()
    snapshot: dict[str, tuple[int, object]] = {}
    with engine.connect() as connection:
        for table in READ_ONLY_TABLES:
            latest = (
                connection.execute(text(f"select max(updated_at) from {table}")).scalar()
                if table in UPDATED_AT_TABLES
                else None
            )
            count = connection.execute(text(f"select count(*) from {table}")).scalar_one()
            snapshot[table] = (int(count), latest)
    return snapshot


def test_overview_is_readable_without_data(client: TestClient) -> None:
    response = client.get("/api/overview", params={"as_of": AS_OF.isoformat()})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["as_of"] == "2026-11-10T23:00:00Z"
    assert [item["inst_type"] for item in body["market_states"]] == ["SPOT", "SWAP"]
    assert [item["inst_type"] for item in body["market"]] == ["SPOT", "SWAP"]
    assert body["portfolio"] == {
        "gross_exposure": "0",
        "net_exposure": "0",
        "open_positions": 0,
        "strategies": [],
    }
    assert body["recent_opportunities"] == []
    assert body["risk_events"] == []


def test_overview_aggregates_the_five_blocks(client: TestClient) -> None:
    _seed_market()
    instance_id = _seed_portfolio(client)
    _seed_risk_event(instance_id)

    response = client.get("/api/overview", params={"as_of": AS_OF.isoformat()})

    assert response.status_code == 200, response.text
    body = response.json()

    # 市场状态：按类别各一条，来源按类别规则取值。
    states = {item["inst_type"]: item for item in body["market_states"]}
    assert states["SPOT"]["session"] == "regular"
    assert states["SPOT"]["primary_source"] == "okx_spot"
    assert states["SWAP"]["session"] == "post"
    assert states["SWAP"]["primary_source"] == "us_equity_proxy"

    # 共振强度：两类各 5 个参与标的，全部上涨。
    market = {item["inst_type"]: item for item in body["market"]}
    assert market["SPOT"]["breadth"]["participants"] == 5
    assert market["SPOT"]["breadth"]["advancers"] == 5
    assert market["SPOT"]["resonance"]["strength"] == "1"
    assert market["SWAP"]["resonance"]["strength"] == "1"

    # 组合概览：一笔买入 2 个 @100，策略预算 1000，净敞口权重 0.2，持仓 1 个。
    assert body["portfolio"]["net_exposure"] == "0.2"
    assert body["portfolio"]["gross_exposure"] == "0.2"
    assert body["portfolio"]["open_positions"] == 1
    assert body["portfolio"]["strategies"][0]["instance_id"] == instance_id

    # 机会流：市场驱动检测为两类各产出一条机会，按 as_of 倒序。
    assert len(body["recent_opportunities"]) == 2
    assert [item["as_of"] for item in body["recent_opportunities"]] == [
        "2026-11-10T23:00:00Z",
        "2026-11-10T23:00:00Z",
    ]
    assert {item["mode"] for item in body["recent_opportunities"]} == {"market"}

    # 风险告警：风控拒绝写入的事件原样读出，未处置。
    assert body["risk_events"]
    assert all(item["resolved_at"] is None for item in body["risk_events"])


def test_overview_is_read_only(client: TestClient) -> None:
    _seed_market()
    instance_id = _seed_portfolio(client)
    _seed_risk_event(instance_id)
    before = _table_snapshot()

    response = client.get("/api/overview", params={"as_of": AS_OF.isoformat()})

    assert response.status_code == 200, response.text
    assert _table_snapshot() == before


def test_overview_is_reproducible_for_the_same_as_of(client: TestClient) -> None:
    _seed_market()
    instance_id = _seed_portfolio(client)
    _seed_risk_event(instance_id)
    params = {"as_of": AS_OF.isoformat()}

    first = client.get("/api/overview", params=params)
    second = client.get("/api/overview", params=params)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()


def test_overview_keeps_older_unresolved_risk_events(client: TestClient) -> None:
    """较早的未处置事件不能被更晚的已处置事件挤出返回结果。"""

    created = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    with session_scope() as session:
        session.add(
            RiskEventRow(
                event_id="re_unresolved_old",
                instance_id=None,
                inst_id=None,
                rule="max_leverage",
                detail="较早的未处置告警",
                created_at=datetime(2026, 11, 1, tzinfo=UTC),
                resolved_at=None,
            )
        )
        for index in range(24):
            session.add(
                RiskEventRow(
                    event_id=f"re_resolved_{index:02d}",
                    instance_id=None,
                    inst_id=None,
                    rule="max_leverage",
                    detail=f"已处置告警 {index}",
                    created_at=created + timedelta(minutes=index),
                    resolved_at=created + timedelta(minutes=index, seconds=30),
                )
            )

    response = client.get("/api/overview", params={"as_of": AS_OF.isoformat()})

    assert response.status_code == 200, response.text
    events = response.json()["risk_events"]
    event_ids = [item["event_id"] for item in events]
    assert len(event_ids) == 6
    assert event_ids[0] == "re_unresolved_old"
    assert events[0]["resolved_at"] is None
    # 剩余名额由最近的已处置事件补足，且立刻排在未处置事件之后。
    assert event_ids[1:] == [f"re_resolved_{index:02d}" for index in (23, 22, 21, 20, 19)]
    assert all(item["resolved_at"] is not None for item in events[1:])
