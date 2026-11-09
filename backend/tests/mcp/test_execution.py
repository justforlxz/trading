"""`execute_strategy_action` 的四道闸门（AC-6 / AC-7）。

闸门顺序固定：实盘授权 -> 未暂停 -> 风控放行 -> 幂等校验；任一步不通过都不落单。
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.execution import service as execution_service
from app.execution.models import Order
from app.strategy.models import Strategy
from tests.execution.conftest import seed_execution_strategy
from tests.mcp.conftest import call_tool, tool_error_code, tool_payload


def _arguments(strategy_id: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "strategy_id": strategy_id,
        "action": "open",
        "reason": "external agent opens the seeded long leg",
        "inst_id": "BTC-USDT-SWAP",
        "side": "buy",
        "quantity": "1",
    }
    payload.update(overrides)
    return payload


async def _order_count(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(Order)) or 0)


def _authorize(monkeypatch, *strategy_ids: int) -> None:
    monkeypatch.setattr(
        execution_service, "authorized_strategy_ids", lambda: frozenset(strategy_ids)
    )


async def test_ac6_strategy_without_live_authorization_is_rejected(
    client, session, operate_token: str, monkeypatch
) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch)
    before = await _order_count(session)

    response = await call_tool(
        client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
    )

    assert tool_error_code(response) == "not_live_authorized"
    assert await _order_count(session) == before


async def test_unknown_strategy_is_rejected_before_any_order(
    client, session, operate_token: str, monkeypatch
) -> None:
    _authorize(monkeypatch, 999_999)
    response = await call_tool(
        client, operate_token, "execute_strategy_action", _arguments(999_999)
    )
    assert tool_error_code(response) == "strategy_not_found"
    assert await _order_count(session) == 0


async def test_authorization_gate_precedes_pause_gate(
    client, session, operate_token: str, monkeypatch
) -> None:
    """未授权且已暂停时，报的是授权缺失（证明闸门顺序固定）。"""

    seeded = await seed_execution_strategy(session)
    strategy = await session.get(Strategy, seeded.strategy_id)
    strategy.paused_at = datetime.now(tz=UTC)
    await session.commit()
    _authorize(monkeypatch)

    response = await call_tool(
        client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
    )
    assert tool_error_code(response) == "not_live_authorized"
    assert await _order_count(session) == 0


async def test_paused_strategy_is_rejected_until_resumed(
    client, session, operate_token: str, monkeypatch
) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch, seeded.strategy_id)

    paused = tool_payload(
        await call_tool(
            client,
            operate_token,
            "pause_strategy",
            {"strategy_id": seeded.strategy_id, "reason": "maintenance window"},
        )
    )
    assert paused["paused"] is True
    assert paused["paused_at"]

    blocked = await call_tool(
        client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
    )
    assert tool_error_code(blocked) == "strategy_paused"
    assert await _order_count(session) == 0

    resumed = tool_payload(
        await call_tool(
            client,
            operate_token,
            "resume_strategy",
            {"strategy_id": seeded.strategy_id, "reason": "maintenance done"},
        )
    )
    assert resumed["paused"] is False

    allowed = tool_payload(
        await call_tool(
            client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
        )
    )
    assert allowed["order"]["mode"] == "paper"


async def test_risk_gate_blocks_unapproved_strategy(
    client, session, operate_token: str, monkeypatch
) -> None:
    seeded = await seed_execution_strategy(session, status="pending_approval")
    _authorize(monkeypatch, seeded.strategy_id)

    response = await call_tool(
        client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
    )
    assert tool_error_code(response) == "not_approved"
    assert await _order_count(session) == 0


async def test_ac7_paper_mode_creates_order_without_touching_exchange(
    client, session, operate_token: str, monkeypatch
) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch, seeded.strategy_id)

    calls: list[tuple[Any, ...]] = []

    def _boom(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - 命中即失败
        calls.append(args)
        raise AssertionError("paper 模式下不得构造真实交易所客户端")

    monkeypatch.setattr(execution_service, "OkxPrivateClient", _boom)

    payload = tool_payload(
        await call_tool(
            client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
        )
    )

    assert payload["mode"] == "paper"
    assert payload["created"] is True
    order = payload["order"]
    assert order["mode"] == "paper"
    assert order["strategy_id"] == seeded.strategy_id
    assert order["intent"] == "entry"
    assert order["state"] in {"submitted", "partial", "filled"}
    assert Decimal(order["filled_quantity"]) > 0

    # mock 交易所 0 次调用，且订单落到本地账本。
    assert calls == []
    assert await _order_count(session) == 1


async def test_duplicate_idempotency_key_is_rejected(
    client, session, operate_token: str, monkeypatch
) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch, seeded.strategy_id)
    arguments = _arguments(seeded.strategy_id, idempotency_key="dup-key-1")

    first = tool_payload(
        await call_tool(client, operate_token, "execute_strategy_action", arguments)
    )
    assert first["created"] is True

    second = await call_tool(client, operate_token, "execute_strategy_action", arguments)
    assert tool_error_code(second) == "duplicate_request"
    assert await _order_count(session) == 1


async def test_execute_requires_reason(client, session, operate_token: str, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch, seeded.strategy_id)

    arguments = _arguments(seeded.strategy_id)
    arguments.pop("reason")
    response = await call_tool(client, operate_token, "execute_strategy_action", arguments)
    assert response.json()["result"]["isError"] is True
    assert await _order_count(session) == 0


async def test_close_without_position_is_rejected(
    client, session, operate_token: str, monkeypatch
) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch, seeded.strategy_id)

    response = await call_tool(
        client,
        operate_token,
        "execute_strategy_action",
        _arguments(seeded.strategy_id, action="close", position_side="long", side=None),
    )
    assert tool_error_code(response) == "no_position"
    assert await _order_count(session) == 0


async def test_unknown_action_is_rejected(client, session, operate_token: str, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)
    _authorize(monkeypatch, seeded.strategy_id)

    response = await call_tool(
        client,
        operate_token,
        "execute_strategy_action",
        _arguments(seeded.strategy_id, action="liquidate"),
    )
    assert tool_error_code(response) == "invalid_action"
    assert await _order_count(session) == 0


async def test_relative_value_signed_weights_can_trade_in_paper(
    client, session, operate_token: str, monkeypatch
) -> None:
    """空头腿负权重不应被当成非法值: 相对价值组合必须能在 paper 下成单。"""

    seeded = await seed_execution_strategy(
        session,
        legs=(
            ("BTC-USDT-SWAP", "long", Decimal("0.2")),
            ("ETH-USDT-SWAP", "short", Decimal("-0.2")),
        ),
    )
    _authorize(monkeypatch, seeded.strategy_id)
    before = await _order_count(session)

    payload = tool_payload(
        await call_tool(
            client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
        )
    )
    assert payload["mode"] == "paper"
    assert payload["created"] is True
    assert await _order_count(session) == before + 1


async def test_risk_status_and_execution_agree_on_drawdown_block(
    client, session, operate_token: str, monkeypatch
) -> None:
    """同一策略同一时刻: 状态查询与执行闸门必须给出同样的回撤结论。"""

    capital = Decimal("100000")
    seeded = await seed_execution_strategy(session, equity=(capital, capital * Decimal("0.7")))
    _authorize(monkeypatch, seeded.strategy_id)

    status = tool_payload(
        await call_tool(client, operate_token, "risk_status", {"strategy_id": seeded.strategy_id})
    )
    assert status["allowed"] is False
    assert status["reason"] == "drawdown"
    assert any(row["code"] == "drawdown_exceeded" for row in status["breaches"])

    before = await _order_count(session)
    response = await call_tool(
        client, operate_token, "execute_strategy_action", _arguments(seeded.strategy_id)
    )
    assert tool_error_code(response) == "risk_blocked"
    details = json.loads(response.json()["result"]["content"][0]["text"])["error"]["details"]
    assert details["reason"] == "drawdown"
    assert any(row["code"] == "drawdown_exceeded" for row in details["breaches"])
    assert await _order_count(session) == before
