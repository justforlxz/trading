"""v6 策略 API：规则校验、不可变版本、标的替换与回测关联。

策略与版本都走真实 HTTP 写入路径；回测行按 `backtest_runs` 的结构直接落库（与
现有回测服务写出的形状一致），再用 `link_backtest` 登记正式关联。断言只针对
请求、库内事实与响应可复算的值。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.backtest import BacktestRunRow
from app.db import session_scope
from app.instrument import sync_instruments
from app.strategy import link_backtest
from tests.factories.instruments import make_ref

INSTRUMENT = "XAAPL-USDT"

RULES: dict[str, Any] = {
    "timeframe": "1d",
    "direction": "long_only",
    "entry": {
        "all": [
            {"left": "MA(20)", "op": ">", "right": "MA(60)"},
            {"left": "RSI(14)", "op": "<", "right": 65},
        ]
    },
    "exit": {
        "any": [
            {"left": "MA(20)", "op": "<", "right": "MA(60)"},
            {"type": "drawdown_stop", "value": 0.08},
        ]
    },
    "position_sizing": {"type": "equal_weight", "weight": 0.3333, "max_positions": 3},
}


@pytest.fixture()
def market(client: TestClient) -> TestClient:
    sync_instruments([make_ref(inst_id=INSTRUMENT)])
    return client


def payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "AAPL 趋势",
        "category": "directional",
        "description": "均线趋势跟随",
        "timeframe": "1d",
        "direction": "long_only",
        "rule_json": RULES,
        "parameters": {"fast": 20, "slow": 60},
        "instrument_ids": [INSTRUMENT],
        "cost_model": {"fee_bps": "10", "slippage_bps": "5"},
        "position_sizing": {"type": "equal_weight", "weight": 0.3333, "max_positions": 3},
        "change_note": "初始版本",
    }
    body.update(overrides)
    return body


def create(market: TestClient, **overrides: Any) -> dict[str, Any]:
    response = market.post("/api/strategies", json=payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def detail(market: TestClient, strategy_id: str) -> dict[str, Any]:
    response = market.get(f"/api/strategies/{strategy_id}")
    assert response.status_code == 200, response.text
    return response.json()


def add_backtest_run(inst_id: str, run_id: str, *, created_at: datetime) -> None:
    metrics = {
        "total_return": "0.124055",
        "max_drawdown": "0.0612",
        "trade_count": "37",
    }
    portfolio = {
        "net_exposure": "0",
        "leg_win_rate": {},
        "long_pnl": "0",
        "short_pnl": "0",
    }
    with session_scope() as session:
        session.add(
            BacktestRunRow(
                run_id=run_id,
                strategy_instance_id="si_legacy",
                strategy_id="legacy",
                strategy_version="1.0.0",
                params_json=json.dumps({}),
                bar="1d",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 11, 1),
                data_source="okx_spot",
                inst_id=inst_id,
                inst_type="SPOT",
                request_json=json.dumps({}),
                data_fingerprint="0" * 64,
                execution_model="next_open",
                costs_json=json.dumps({}),
                metrics_json=json.dumps(metrics),
                portfolio_json=json.dumps(portfolio),
                funding_total=Decimal("0"),
                result_hash="1" * 64,
                created_at=int(created_at.timestamp()),
            )
        )


def test_create_strategy_returns_first_draft_version(market: TestClient) -> None:
    created = create(market)

    assert created["status"] == "draft"
    body = detail(market, created["id"])
    assert body["current_version"] == 1
    assert body["current_version_id"] == created["version_id"]
    assert body["rule_json"]["entry"]["all"][0]["left"] == "MA(20)"
    assert body["instrument_ids"] == [INSTRUMENT]
    assert body["versions"] == [
        {
            "version_id": created["version_id"],
            "version": 1,
            "timeframe": "1d",
            "direction": "long_only",
            "change_note": "初始版本",
            "created_at": created["created_at"],
        }
    ]


def test_list_returns_current_version_and_instrument_count(market: TestClient) -> None:
    created = create(market)

    response = market.get("/api/strategies")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    assert body["items"][0]["id"] == created["id"]
    assert body["items"][0]["instrument_count"] == 1
    assert body["items"][0]["latest_backtest"] is None


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (
            {
                **RULES,
                "entry": {"all": [{"left": "NOPE(20)", "op": ">", "right": 1}]},
            },
            "未注册",
        ),
        (
            {
                **RULES,
                "entry": {"all": [{"left": "MA(20)", "op": "!=", "right": 1}]},
            },
            "op",
        ),
        (
            {
                **RULES,
                "position_sizing": {"type": "equal_weight", "weight": 1.5, "max_positions": 3},
            },
            "weight",
        ),
        ({**RULES, "unknown": True}, "未知字段"),
    ],
)
def test_rule_json_rejects_invalid_input(
    market: TestClient, rule: dict[str, Any], message: str
) -> None:
    response = market.post("/api/strategies", json=payload(rule_json=rule))

    assert response.status_code == 400, response.text
    assert message in response.json()["detail"]


def test_rule_json_rejects_unknown_position_sizing_field(market: TestClient) -> None:
    sizing = {"type": "equal_weight", "weight": 0.5, "max_positions": 2, "leverage": 3}

    response = market.post("/api/strategies", json=payload(position_sizing=sizing))

    assert response.status_code == 400
    assert "未知字段" in response.json()["detail"]


def test_new_version_increments_and_keeps_old_rule(market: TestClient) -> None:
    created = create(market)
    first = detail(market, created["id"])
    changed_rule = {
        **RULES,
        "entry": {"all": [{"left": "EMA(20)", "op": ">", "right": "EMA(60)"}]},
    }

    response = market.post(
        f"/api/strategies/{created['id']}/versions",
        json={"rule_json": changed_rule, "change_note": "改用 EMA"},
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["version"] == 2
    assert version["rule_json"]["entry"]["all"][0]["left"] == "EMA(20)"
    after = detail(market, created["id"])
    assert after["current_version"] == 2
    assert after["versions"][0]["version"] == 2
    assert after["versions"][1]["version_id"] == first["current_version_id"]

    versions = market.get(f"/api/strategies/{created['id']}/versions").json()["items"]
    old = next(item for item in versions if item["version"] == 1)
    assert old["rule_json"]["entry"]["all"][0]["left"] == "MA(20)"


def test_put_metadata_does_not_create_a_version(market: TestClient) -> None:
    created = create(market)

    response = market.put(
        f"/api/strategies/{created['id']}",
        json={"name": "改名", "status": "validated", "description": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_id"] == created["version_id"]
    body = detail(market, created["id"])
    assert body["name"] == "改名"
    assert body["status"] == "validated"
    assert body["description"] is None
    assert len(body["versions"]) == 1


def test_put_with_rule_creates_a_new_version(market: TestClient) -> None:
    created = create(market)
    changed = {**RULES, "exit": {"any": [{"left": "RSI(14)", "op": ">", "right": 70}]}}

    response = market.put(
        f"/api/strategies/{created['id']}",
        json={"rule_json": changed, "change_note": "换出场"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["version_id"] != created["version_id"]
    assert detail(market, created["id"])["current_version"] == 2


def test_version_instruments_replace_is_transactional(market: TestClient) -> None:
    created = create(market)
    version = created["version_id"]

    failed = market.put(
        f"/api/strategies/{created['id']}/versions/1/instruments",
        json={"instrument_ids": ["NOPE-USDT"]},
    )

    assert failed.status_code == 400, failed.text
    assert detail(market, created["id"])["instrument_ids"] == [INSTRUMENT]

    replaced = market.put(
        f"/api/strategies/{created['id']}/versions/1/instruments",
        json={"instrument_ids": []},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["version_id"] == version
    assert replaced.json()["instrument_ids"] == []


def test_old_version_instruments_are_immutable(market: TestClient) -> None:
    created = create(market)
    market.post(f"/api/strategies/{created['id']}/versions", json={"change_note": "第二版"})

    response = market.put(
        f"/api/strategies/{created['id']}/versions/1/instruments",
        json={"instrument_ids": []},
    )

    assert response.status_code == 409, response.text
    versions = market.get(f"/api/strategies/{created['id']}/versions").json()["items"]
    old = next(item for item in versions if item["version"] == 1)
    assert old["instrument_ids"] == [INSTRUMENT]


def test_old_version_backtest_stays_on_the_old_version(market: TestClient) -> None:
    created = create(market)
    strategy_id = created["id"]
    first_version = created["version_id"]
    now = datetime.now(UTC).replace(microsecond=0)
    add_backtest_run(INSTRUMENT, "bt_v1", created_at=now)
    assert link_backtest(first_version, "bt_v1") is True

    market.post(f"/api/strategies/{strategy_id}/versions", json={"change_note": "第二版"})

    body = detail(market, strategy_id)
    assert body["latest_backtest"]["run_id"] == "bt_v1"
    assert body["latest_backtest"]["strategy_version_id"] == first_version
    assert body["latest_backtest"]["total_return_pct"] == "12.4055"
    assert body["latest_backtest"]["max_drawdown_pct"] == "6.12"
    assert body["latest_backtest"]["trade_count"] == 37


def test_instrument_strategies_only_consider_the_last_month(market: TestClient) -> None:
    created = create(market)
    old = datetime.now(UTC).replace(microsecond=0) - timedelta(days=31)
    add_backtest_run(INSTRUMENT, "bt_old", created_at=old)
    link_backtest(created["version_id"], "bt_old")

    response = market.get(f"/api/instruments/{INSTRUMENT}/strategies")

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["strategy_id"] == created["id"]
    assert item["linked_version_ids"] == [created["version_id"]]
    assert item["recent_backtest"] is None

    add_backtest_run(INSTRUMENT, "bt_new", created_at=datetime.now(UTC).replace(microsecond=0))
    link_backtest(created["version_id"], "bt_new")
    item = market.get(f"/api/instruments/{INSTRUMENT}/strategies").json()["items"][0]
    assert item["recent_backtest"]["run_id"] == "bt_new"
    assert item["recent_backtest"]["strategy_version_id"] == created["version_id"]


def test_unknown_strategy_is_404(market: TestClient) -> None:
    assert market.get("/api/strategies/st_missing").status_code == 404
    assert market.put("/api/strategies/st_missing", json={"name": "x"}).status_code == 404
    assert market.get("/api/strategies/st_missing/versions").status_code == 404


def test_old_instance_routes_are_gone(market: TestClient) -> None:
    assert market.get("/api/strategy-instances").status_code == 404
    assert market.post("/api/strategy-instances", json={}).status_code == 404
