"""P4-05: 策略草案只建议、不落库。"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ai.conftest import seed_opportunity, seed_relations, seed_target


async def _counts(session: AsyncSession) -> tuple[int, int, int]:
    from app.strategy.models import Strategy, StrategyApproval, StrategyLeg

    async def count(model) -> int:
        return await session.scalar(select(func.count()).select_from(model)) or 0

    return (
        await count(Strategy),
        await count(StrategyLeg),
        await count(StrategyApproval),
    )


async def test_suggest_from_target_returns_draft_and_persists_nothing(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    target = await seed_target(session, symbol="AAPL")
    await seed_relations(session, target_id=target.target_id)
    configure_ai()

    before = await _counts(session)
    response = await client.post(
        "/api/v1/ai/suggest/strategy", json={"target_id": target.target_id}
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["draft_only"] is True
    assert payload["persisted"] is False
    assert len(payload["legs"]) == 2
    assert {leg["side"] for leg in payload["legs"]} == {"long", "short"}
    assert all(leg["target_weight"] == "0.50" for leg in payload["legs"])
    assert any(item["type"] == "relation_edge" for item in payload["citations"])
    assert payload["warnings"]

    assert await _counts(session) == before


async def test_suggest_without_snapshot_reports_missing_data(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    target = await seed_target(session, symbol="AAPL")
    configure_ai()

    before = await _counts(session)
    response = await client.post(
        "/api/v1/ai/suggest/strategy", json={"target_id": target.target_id}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft_only"] is True
    assert payload["legs"] == []
    assert payload["missing"] == ["relations_snapshot"]
    assert await _counts(session) == before


async def test_suggest_from_opportunity_returns_single_leg_draft(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    target = await seed_target(session, symbol="NVDA")
    opportunity_id = await seed_opportunity(
        session, instrument_id=target.instrument_id, direction="long"
    )
    configure_ai()

    before = await _counts(session)
    response = await client.post(
        "/api/v1/ai/suggest/strategy", json={"opportunity_id": opportunity_id}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft_only"] is True
    assert payload["persisted"] is False
    assert len(payload["legs"]) == 1
    assert payload["legs"][0]["side"] == "long"
    assert payload["legs"][0]["target_weight"] == "0.50"
    assert any("单边" in item for item in payload["warnings"])
    assert await _counts(session) == before


async def test_suggest_validation_and_unknown_entities(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    configure_ai()

    missing = await client.post("/api/v1/ai/suggest/strategy", json={})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "ai_invalid_request"

    unknown_target = await client.post("/api/v1/ai/suggest/strategy", json={"target_id": 999999})
    assert unknown_target.status_code == 404
    assert unknown_target.json()["error"]["code"] == "ai_target_not_found"

    unknown_opportunity = await client.post(
        "/api/v1/ai/suggest/strategy", json={"opportunity_id": 999999}
    )
    assert unknown_opportunity.status_code == 404
    assert unknown_opportunity.json()["error"]["code"] == "ai_opportunity_not_found"

    assert await _counts(session) == (0, 0, 0)
