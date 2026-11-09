"""`trigger_scan`（AC-4）：新增批次、机会可查、同幂等键不产生第二条。"""

from sqlalchemy import func, select

from app.mcp.tools import SCAN_JOB_NAME
from app.opportunity.models import Opportunity, OpportunityRun
from tests.mcp.conftest import call_tool, tool_payload
from tests.opportunity.test_scanner import _seed_two_groups


async def _count_runs(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(OpportunityRun)) or 0)


async def test_ac4_trigger_scan_creates_batch_and_opportunities(
    client, session, operate_token: str
) -> None:
    await _seed_two_groups(session)
    assert await _count_runs(session) == 0

    response = await call_tool(
        client,
        operate_token,
        "trigger_scan",
        {"idempotency_key": "scan-1", "reason": "scheduled external scan"},
    )
    payload = tool_payload(response)
    assert payload["status"] in {"ok", "partial"}
    assert payload["run_id"] > 0
    assert payload["counts"]["universe"] == 6

    # 数据库新增一条批记录，且该批次确有机会落库。
    assert await _count_runs(session) == 1
    stored = await session.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.run_id == payload["run_id"])
    )
    assert int(stored or 0) > 0

    # `list_opportunities` 能查到同一批机会。
    listing = tool_payload(await call_tool(client, operate_token, "list_opportunities", {}))
    assert listing["run_id"] == payload["run_id"]
    assert listing["items"]
    assert listing["items"][0]["reasons"]


async def test_ac4_same_idempotency_key_does_not_create_a_second_scan(
    client, session, operate_token: str
) -> None:
    await _seed_two_groups(session)

    first = tool_payload(
        await call_tool(
            client,
            operate_token,
            "trigger_scan",
            {"idempotency_key": "scan-dup", "reason": "first"},
        )
    )
    second = tool_payload(
        await call_tool(
            client,
            operate_token,
            "trigger_scan",
            {"idempotency_key": "scan-dup", "reason": "retry"},
        )
    )

    assert second["status"] == "skipped"
    assert second["run_id"] == first["run_id"]
    assert await _count_runs(session) == 1
    from app.ops.models import JobRun

    jobs = await session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_name == SCAN_JOB_NAME)
    )
    assert int(jobs or 0) == 1


async def test_trigger_scan_without_any_candles_fails_cleanly(
    client, session, operate_token: str
) -> None:
    from tests.market.support import insert_instrument

    await insert_instrument(session, "AAPL-USDT-SWAP")

    response = await call_tool(
        client,
        operate_token,
        "trigger_scan",
        {"idempotency_key": "scan-empty", "reason": "probe"},
    )
    body = response.json()["result"]
    assert body["isError"] is True
    assert "scan_no_data" in body["content"][0]["text"]
    assert await _count_runs(session) == 0

    from app.ops.models import JobRun

    job = await session.scalar(select(JobRun).where(JobRun.job_name == SCAN_JOB_NAME))
    assert job is not None
    assert job.status == "failed"
