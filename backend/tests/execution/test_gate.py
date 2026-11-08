"""真实交易门禁：默认关闭、缺凭据、未授权、差异未处理四道闸门。"""

import pytest

from app.config import Settings
from app.execution import gate
from tests.execution.conftest import seed_execution_strategy

CREDENTIALS = {"okx_api_key": "k", "okx_api_secret": "s", "okx_api_passphrase": "p"}


def _check(**overrides):
    kwargs = {
        "requested_mode": gate.MODE_REAL,
        "real_trading_enabled": False,
        "credentials_ready": True,
        "strategy_id": 7,
        "authorized_strategy_ids": frozenset({7}),
        "open_diffs": 0,
    }
    kwargs.update(overrides)
    return gate.check_submit(**kwargs)


def test_real_order_rejected_when_switch_off() -> None:
    decision = _check(real_trading_enabled=False)
    assert decision.allowed is False
    assert decision.code == gate.CODE_REAL_DISABLED


def test_real_order_rejected_without_credentials() -> None:
    decision = _check(real_trading_enabled=True, credentials_ready=False)
    assert decision.code == gate.CODE_CREDENTIALS_MISSING


def test_real_order_rejected_for_unauthorized_strategy() -> None:
    decision = _check(real_trading_enabled=True, authorized_strategy_ids=frozenset({8}))
    assert decision.code == gate.CODE_STRATEGY_NOT_AUTHORIZED


def test_real_order_rejected_with_open_diffs() -> None:
    decision = _check(real_trading_enabled=True, open_diffs=1)
    assert decision.code == gate.CODE_RECONCILE_PENDING


def test_real_order_allowed_when_all_gates_pass() -> None:
    decision = _check(real_trading_enabled=True)
    assert decision.allowed is True
    assert decision.mode == gate.MODE_REAL


def test_paper_order_bypasses_real_gates() -> None:
    decision = _check(requested_mode=gate.MODE_PAPER, real_trading_enabled=False)
    assert decision.allowed is True


def test_parse_strategy_ids_ignores_invalid() -> None:
    assert gate.parse_strategy_ids("1, 2,abc,,0,-3") == frozenset({1, 2})
    assert gate.parse_strategy_ids(None) == frozenset()


async def test_real_order_without_body_returns_403(client) -> None:
    response = await client.post("/api/v1/execution/orders")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "real_trading_disabled"


async def test_real_order_with_body_returns_403(client, session) -> None:
    seeded = await seed_execution_strategy(session)
    response = await client.post(
        "/api/v1/execution/orders",
        json={
            "strategy_id": seeded.strategy_id,
            "inst_id": "BTC-USDT-SWAP",
            "side": "buy",
            "position_side": "long",
            "quantity": "1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "real_trading_disabled"


def _real_settings(**overrides) -> Settings:
    values = {"real_trading_enabled": True, "okx_api_key": "", "okx_api_secret": ""}
    values.update(overrides)
    return Settings(**values)


async def _enable_real(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.api.v1.execution.get_settings", lambda: settings)
    monkeypatch.setattr("app.execution.service.settings", lambda: settings)
    monkeypatch.setattr("app.execution.paper.get_settings", lambda: settings)


async def test_real_enabled_without_credentials_is_rejected(client, session, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)
    await _enable_real(monkeypatch, _real_settings())
    response = await client.post(
        "/api/v1/execution/orders",
        json={
            "strategy_id": seeded.strategy_id,
            "inst_id": "BTC-USDT-SWAP",
            "side": "buy",
            "position_side": "long",
            "quantity": "1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "execution_credentials_missing"


async def test_real_enabled_but_strategy_not_authorized(client, session, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)
    await _enable_real(monkeypatch, _real_settings(**CREDENTIALS, execution_real_strategy_ids=""))
    response = await client.post(
        "/api/v1/execution/orders",
        json={
            "strategy_id": seeded.strategy_id,
            "inst_id": "BTC-USDT-SWAP",
            "side": "buy",
            "position_side": "long",
            "quantity": "1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "execution_strategy_not_authorized"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", frozenset({5})), ("", frozenset()), ("x,9", frozenset({9}))],
)
def test_authorization_list_parsing(raw: str, expected: frozenset[int]) -> None:
    assert gate.parse_strategy_ids(raw) == expected
