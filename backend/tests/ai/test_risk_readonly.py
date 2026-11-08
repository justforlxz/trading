"""P4-03: 行数门禁 —— 只读问答不得为满足查询而写业务表。

- 问风控前后 `risk.risk_policy` 行数不变 (缺省阈值用未落库的临时对象);
- 问市场前后 `market.market_session` 行数不变 (只读日历, 不再 `sync_sessions`)。
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_risk_question_does_not_create_policy_row(
    client: AsyncClient, session: AsyncSession, configure_ai
) -> None:
    from app.risk.models import RiskPolicy

    configure_ai()
    before = await _count(session, RiskPolicy)
    assert before == 0

    response = await client.post("/api/v1/ai/query", json={"question": "当前风控敞口是多少"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answerable"] is True
    assert payload["intent"] == "risk"

    assert await _count(session, RiskPolicy) == before


async def test_market_question_does_not_write_sessions(
    client: AsyncClient, session: AsyncSession, configure_ai
) -> None:
    from app.market.models import MarketSession

    configure_ai()
    # 先走官方只读接口让日历落库 (该接口按设计会 upsert), 再验证问答不再写入。
    truth = await client.get("/api/v1/market/sessions")
    assert truth.status_code == 200, truth.text
    before = await _count(session, MarketSession)
    assert before > 0

    response = await client.post("/api/v1/ai/query", json={"question": "当前市场行情怎么样"})
    assert response.status_code == 200, response.text
    assert response.json()["answerable"] is True

    assert await _count(session, MarketSession) == before
