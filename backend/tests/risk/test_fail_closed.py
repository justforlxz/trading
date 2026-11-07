"""fail-closed 与确定性用例（AC-7/AC-8）：依赖缺失或计算异常一律拒绝放行。"""

import pytest
from sqlalchemy import select

from app.risk import service
from app.risk.errors import RiskError
from app.risk.models import RiskEvent
from tests.risk.conftest import seed_strategy


async def test_missing_candles_denies(session) -> None:
    seeded = await seed_strategy(session, candles=False)
    result = await service.evaluate(session, strategy_id=seeded.strategy_id)
    assert result["allowed"] is False
    assert result["reason"] == "market_data_unavailable"
    assert set(result["details"]["missing"]) == {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}


async def test_missing_backtest_denies(session) -> None:
    seeded = await seed_strategy(session, backtest=False)
    result = await service.evaluate(session, strategy_id=seeded.strategy_id)
    assert result["allowed"] is False
    assert result["reason"] == "no_equity_series"


async def test_unapproved_strategy_is_rejected(session) -> None:
    seeded = await seed_strategy(session, status="draft")
    with pytest.raises(RiskError) as excinfo:
        await service.evaluate(session, strategy_id=seeded.strategy_id)
    assert excinfo.value.code == "strategy_not_approved"
    assert excinfo.value.status_code == 409


async def test_unknown_strategy_is_404(session) -> None:
    with pytest.raises(RiskError) as excinfo:
        await service.evaluate(session, strategy_id=9999)
    assert excinfo.value.code == "not_found"
    assert excinfo.value.status_code == 404


async def test_computation_exception_is_fail_closed(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await seed_strategy(session)

    def boom(**_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(service.limits, "evaluate_limits", boom)
    result = await service.evaluate(session, strategy_id=seeded.strategy_id)
    assert result["allowed"] is False
    assert result["reason"] == "risk_evaluation_failed"
    rows = (await session.execute(select(RiskEvent))).scalars().all()
    assert rows == []


async def test_repeated_evaluation_is_deterministic_and_idempotent(session) -> None:
    seeded = await seed_strategy(session)

    first = await service.evaluate(
        session, strategy_id=seeded.strategy_id, evaluation_key="2026-11-07"
    )
    second = await service.evaluate(
        session, strategy_id=seeded.strategy_id, evaluation_key="2026-11-07"
    )

    assert first["allowed"] is False
    assert first["reason"] == "limit_breach"
    assert first == second

    rows = (await session.execute(select(RiskEvent))).scalars().all()
    assert len(rows) == len(first["events"])
    assert len({row.id for row in rows}) == len(rows)


async def test_limit_breach_and_drawdown_both_recorded(session) -> None:
    seeded = await seed_strategy(
        session, equity=(service._decimal("100000"), service._decimal("80000"))
    )
    result = await service.evaluate(
        session, strategy_id=seeded.strategy_id, evaluation_key="2026-11-07"
    )

    codes = {item["code"] for item in result["breaches"]}
    assert "concentration_exceeded" in codes
    assert result["drawdown_action"] == "close"
    assert result["reason"] == "limit_breach"

    rows = (await session.execute(select(RiskEvent))).scalars().all()
    kinds = {row.kind for row in rows}
    assert kinds == {"limit_breach", "drawdown"}
    drawdown_row = next(row for row in rows if row.kind == "drawdown")
    assert drawdown_row.action == "close"
    assert drawdown_row.severity == "tier3"
