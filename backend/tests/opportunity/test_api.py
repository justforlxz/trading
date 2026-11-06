"""机会 API 契约（P1-13）：可解释响应、参数边界、幂等扫描与批次查询。"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.analysis.core.opportunities import UnexplainableCandidate
from app.jobs import tasks
from app.opportunity import api as opportunity_api
from app.opportunity.models import Opportunity, OpportunityRun
from tests.opportunity.test_scanner import _seed_two_groups


@pytest.fixture
def inline_dispatch(monkeypatch):
    """后台投递换成同进程同步执行：202 返回时扫描已经完成。"""

    calls: list[tuple[str, dict]] = []

    async def fake(task_name: str, **kwargs):
        calls.append((task_name, kwargs))
        await getattr(tasks, task_name)({}, **kwargs)

    monkeypatch.setattr(opportunity_api, "dispatch", fake)
    return calls


async def _scan(client) -> dict:
    response = await client.post("/api/v1/opportunities/scan", json={})
    assert response.status_code in (200, 202)
    return response.json()


async def test_scan_returns_202_and_duplicate_request_hits_existing_batch(
    client, session, inline_dispatch
) -> None:
    await _seed_two_groups(session)

    first = await client.post("/api/v1/opportunities/scan", json={})
    assert first.status_code == 202
    body = first.json()
    assert body["job_name"] == tasks.SCAN_OPPORTUNITIES
    assert body["job_id"] > 0
    assert first.headers["location"] == f"/api/v1/ops/job-runs/{body['job_id']}"

    second = await client.post("/api/v1/opportunities/scan", json={})
    assert second.status_code == 200
    assert second.json()["status"] == "skipped"

    assert await session.scalar(select(func.count()).select_from(OpportunityRun)) == 1


async def test_opportunities_are_explainable_and_sorted_by_score(
    client, session, inline_dispatch
) -> None:
    await _seed_two_groups(session)
    await _scan(client)

    response = await client.get("/api/v1/opportunities", params={"limit": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["items"], "扫描后必须能查到机会"
    scores = [Decimal(item["score"]) for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    for item in body["items"]:
        assert item["reasons"], "不允许返回没有理由的机会"
        assert any(
            isinstance(value, int | float) and not isinstance(value, bool)
            for value in item["evidence"].values()
        ), "证据里至少要有可复算的数值"


async def test_opportunity_detail_exposes_members(client, session, inline_dispatch) -> None:
    await _seed_two_groups(session)
    await _scan(client)
    listing = (await client.get("/api/v1/opportunities")).json()
    opportunity_id = listing["items"][0]["id"]

    response = await client.get(f"/api/v1/opportunities/{opportunity_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == opportunity_id
    assert "members" in body
    assert body["reasons"]


async def test_unknown_opportunity_returns_404(client) -> None:
    response = await client.get("/api/v1/opportunities/999999")
    assert response.status_code == 404


@pytest.mark.parametrize("limit", [0, 201])
async def test_out_of_range_limit_is_rejected(client, limit: int) -> None:
    response = await client.get("/api/v1/opportunities", params={"limit": limit})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"kind": "bogus"},
        {"direction": "sideways"},
        {"min_score": "not-a-number"},
    ],
)
async def test_illegal_filters_are_422_not_500(client, params: dict) -> None:
    response = await client.get("/api/v1/opportunities", params=params)
    assert response.status_code == 422


async def test_runs_and_clusters_endpoints(client, session, inline_dispatch) -> None:
    await _seed_two_groups(session)
    accepted = await _scan(client)

    runs = (await client.get("/api/v1/opportunities/runs")).json()
    assert runs["items"]
    run_id = runs["items"][0]["id"]
    assert runs["items"][0]["status"] in {"ok", "partial"}
    assert runs["items"][0]["universe_size"] == 6

    detail = await client.get(f"/api/v1/opportunities/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["counts"]["snapshot"] == 6

    missing = await client.get("/api/v1/opportunities/runs/999999")
    assert missing.status_code == 404

    clusters = (await client.get("/api/v1/clusters", params={"run_id": run_id})).json()
    assert len(clusters["items"]) == 2
    for cluster in clusters["items"]:
        assert cluster["members"]
        assert cluster["label"].startswith("cluster-")

    job = await client.get(f"/api/v1/ops/job-runs/{accepted['job_id']}")
    assert job.status_code == 200
    assert job.json()["result"]["run_id"] == run_id


async def test_market_snapshot_serves_the_latest_cross_section(
    client, session, inline_dispatch
) -> None:
    await _seed_two_groups(session)
    await _scan(client)

    response = await client.get("/api/v1/market/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] is not None
    assert body["count"] == 6
    assert body["breadth"]["total"] == 6
    assert {item["symbol"] for item in body["items"]} == {
        "UP1",
        "UP2",
        "UP3",
        "DN1",
        "DN2",
        "DN3",
    }


async def test_empty_snapshot_returns_empty_state(client) -> None:
    response = await client.get("/api/v1/market/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] is None
    assert body["items"] == []
    assert body["count"] == 0
    assert body["breadth"] is None
    assert body["session"] in {"PRE", "REGULAR", "POST", "CLOSED"}


def test_payload_builder_fails_loudly_when_reasons_are_gone() -> None:
    """AC8：把 reasons 去掉后，响应构造必须失败，而不是退回裸分数。"""

    row = SimpleNamespace(
        id=1,
        run_id=1,
        kind="directional",
        direction="long",
        score=Decimal("0.9"),
        horizon="5d",
        reasons=[],
        evidence={"resonance_strength": 0.9},
        primary_instrument_id=1,
        created_at=None,
    )
    with pytest.raises(UnexplainableCandidate):
        opportunity_api.opportunity_payload(row, None)


async def test_opportunity_rows_without_reasons_are_never_returned(client, session) -> None:
    """即使库里被塞进残缺记录，列表也不会把它当成正常机会输出。"""

    from tests.market.support import insert_instrument

    instrument = await insert_instrument(session, "AAPL-USDT-SWAP")
    run = OpportunityRun(
        run_key="broken",
        as_of=datetime.now(UTC),
        universe_size=1,
        params={},
        status="ok",
        counts={},
    )
    session.add(run)
    await session.flush()
    session.add(
        Opportunity(
            run_id=run.id,
            kind="directional",
            primary_instrument_id=instrument.id,
            direction="long",
            score=Decimal("1.0"),
            horizon="5d",
            reasons=[],
            evidence={},
            dedupe_key="broken",
        )
    )
    await session.commit()

    with pytest.raises(UnexplainableCandidate):
        await client.get("/api/v1/opportunities")
