"""策略 API 契约（AC3/AC4/AC5/AC6/AC7/AC9/AC10）：生成、审批、只读与审计。"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.db.session import session_factory
from app.opportunity.models import Opportunity, OpportunityRun
from app.research.models import (
    MarketSnapshot,
    RelationEdge,
    RelationSnapshot,
    RelativeStrengthSnapshot,
    TargetSymbol,
)
from app.strategy import service
from app.strategy.core.constraints import ConstraintViolation
from app.strategy.models import StrategyTransition
from tests.market.support import insert_instrument

NOW = datetime(2026, 10, 1, tzinfo=UTC)


async def _seed_target(session, *, rs_ratio: str = "1.2") -> TargetSymbol:
    """目标 + 一条相关性边 + 两侧截面快照 + 相对强弱。"""

    anchor = await insert_instrument(session, "AAPL-USDT-SWAP")
    peer = await insert_instrument(session, "MSFT-USDT-SWAP")
    target = TargetSymbol(symbol="AAPL", exchange="XNAS", instrument_id=anchor.id)
    session.add(target)
    await session.flush()

    snapshot = RelationSnapshot(
        target_id=target.id,
        as_of=NOW,
        window_bars=60,
        method="pearson",
        price_basis="okx_close",
        lag_max=5,
        sample_size=60,
        run_key="relations-1",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        RelationEdge(
            snapshot_id=snapshot.id,
            counterparty_id=peer.id,
            coefficient=Decimal("0.87"),
            best_lag=-1,
            stability=Decimal("0.75"),
            rank=1,
        )
    )
    session.add_all(
        [
            MarketSnapshot(
                as_of=NOW,
                instrument_id=anchor.id,
                ret_1d=Decimal("0.01"),
                ret_5d=Decimal("0.03"),
                ret_20d=Decimal("0.08"),
                vol_20d=Decimal("0.02"),
            ),
            MarketSnapshot(
                as_of=NOW,
                instrument_id=peer.id,
                ret_1d=Decimal("-0.01"),
                ret_5d=Decimal("-0.01"),
                ret_20d=Decimal("-0.04"),
                vol_20d=Decimal("0.03"),
            ),
        ]
    )
    session.add(
        RelativeStrengthSnapshot(
            target_id=target.id,
            counterparty_id=peer.id,
            as_of=NOW,
            lookback_bars=60,
            rs_ratio=Decimal(rs_ratio),
            rs_momentum=Decimal("0.05"),
            run_key="rs-1",
        )
    )
    await session.commit()
    return target


async def _seed_opportunity(session) -> tuple[int, int]:
    anchor = await insert_instrument(session, "AAPL-USDT-SWAP")
    peer = await insert_instrument(session, "MSFT-USDT-SWAP")
    run = OpportunityRun(
        run_key="run-1",
        as_of=NOW,
        universe_size=2,
        params={"lookback_bars": 60},
        status="ok",
    )
    session.add(run)
    await session.flush()
    row = Opportunity(
        run_id=run.id,
        kind="relative_value",
        primary_instrument_id=anchor.id,
        direction="pair",
        score=Decimal("2.5"),
        horizon="swing",
        reasons=["spread widening"],
        evidence={
            "cluster": "c1",
            "spread_z": 2.1,
            "correlation": 0.81,
            "overlap_bars": 55,
            "long_inst_id": "AAPL-USDT-SWAP",
            "short_inst_id": "MSFT-USDT-SWAP",
            "long_instrument_id": anchor.id,
            "short_instrument_id": peer.id,
        },
        dedupe_key="d1",
    )
    session.add(row)
    await session.commit()
    return run.id, row.id


async def _create(client, target_id: int | None = None, **overrides):
    payload = {
        "kind": "relative_value",
        "name": "demo",
        "target_id": target_id,
        "templates": ["relative_value"],
        "params": {},
    }
    payload.update(overrides)
    return await client.post("/api/v1/strategies", json=payload)


async def test_create_from_target_returns_draft_with_legs(client, session) -> None:
    target = await _seed_target(session)

    response = await _create(client, target.id)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["kind"] == "relative_value"
    assert body["source"]["type"] == "target"
    assert body["content_hash"]
    assert body["strategy_key"]
    assert body["version"] == 1
    assert body["approved_at"] is None
    assert len(body["legs"]) == 2

    total = sum(abs(Decimal(leg["weight"])) for leg in body["legs"])
    assert total == Decimal("1.0000000000")
    for leg in body["legs"]:
        assert leg["rationale"]
        assert "window=60" in leg["rationale"]
        assert leg["side"] in ("long", "short")
    assert {leg["side"] for leg in body["legs"]} == {"long", "short"}


async def test_same_input_is_idempotent_and_threshold_change_makes_new_key(client, session) -> None:
    target = await _seed_target(session)

    first = await _create(client, target.id)
    second = await _create(client, target.id)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["strategy_key"] == first.json()["strategy_key"]

    changed = await _create(client, target.id, params={"max_position_weight": 0.55})
    assert changed.status_code == 201
    assert changed.json()["id"] != first.json()["id"]
    assert changed.json()["strategy_key"] != first.json()["strategy_key"]


async def test_approval_flow_and_content_becomes_read_only(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]

    submitted = await client.post(f"/api/v1/strategies/{strategy_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_approval"
    assert submitted.json()["transitions"][-1]["actor"] == "user"

    approved = await client.post(
        f"/api/v1/strategies/{strategy_id}/approve",
        json={"reviewer": "alice", "note": "风险可控"},
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved"
    assert body["approved_at"]
    assert body["reviewer"] == "alice"
    assert body["approvals"][0]["decision"] == "approved"
    assert body["approvals"][0]["content_hash"] == body["content_hash"]

    blocked = await client.patch(f"/api/v1/strategies/{strategy_id}", json={"name": "renamed"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "strategy_readonly"

    unchanged = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()
    assert unchanged["name"] == "demo"
    assert unchanged["content_hash"] == body["content_hash"]

    archived = await client.post(f"/api/v1/strategies/{strategy_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    after_archive = await client.patch(
        f"/api/v1/strategies/{strategy_id}", json={"params": {"min_legs": 3}}
    )
    assert after_archive.status_code == 409
    assert after_archive.json()["error"]["code"] == "strategy_readonly"


async def test_illegal_transition_changes_nothing(client, session) -> None:
    target = await _seed_target(session)
    strategy_id = (await _create(client, target.id)).json()["id"]

    response = await client.post(f"/api/v1/strategies/{strategy_id}/archive")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "strategy_illegal_transition"
    detail = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()
    assert detail["status"] == "draft"
    assert detail["transitions"] == []
    assert detail["approvals"] == []


async def test_rejected_content_is_editable_and_hash_scoped(client, session) -> None:
    target = await _seed_target(session)
    strategy_id = (await _create(client, target.id)).json()["id"]
    first_hash = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()["content_hash"]

    await client.post(f"/api/v1/strategies/{strategy_id}/submit")
    rejected = await client.post(
        f"/api/v1/strategies/{strategy_id}/reject",
        json={"reviewer": "bob", "note": "敞口偏高"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approvals"][0]["decision"] == "rejected"
    assert rejected.json()["approvals"][0]["content_hash"] == first_hash

    edited = await client.patch(
        f"/api/v1/strategies/{strategy_id}", json={"params": {"max_position_weight": 0.55}}
    )
    assert edited.status_code == 200
    assert edited.json()["version"] == 2
    assert edited.json()["status"] == "rejected"
    second_hash = edited.json()["content_hash"]
    assert second_hash != first_hash

    approvals = (await client.get(f"/api/v1/strategies/{strategy_id}/approvals")).json()
    assert len(approvals["items"]) == 1
    assert approvals["items"][0]["content_hash"] == first_hash
    assert approvals["items"][0]["content_hash"] != second_hash

    # rejected 是终态：AC4 明确 rejected→pending_approval 非法，重新提审要先归档再新建。
    resubmit = await client.post(f"/api/v1/strategies/{strategy_id}/submit")
    assert resubmit.status_code == 409
    assert resubmit.json()["error"]["code"] == "strategy_illegal_transition"

    archived = await client.post(f"/api/v1/strategies/{strategy_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    blocked = await client.patch(f"/api/v1/strategies/{strategy_id}", json={"name": "again"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "strategy_readonly"


async def test_transitions_are_append_only_and_match_the_database(client, session) -> None:
    target = await _seed_target(session)
    strategy_id = (await _create(client, target.id)).json()["id"]

    await client.post(f"/api/v1/strategies/{strategy_id}/submit")
    await client.post(
        f"/api/v1/strategies/{strategy_id}/reject",
        json={"reviewer": "bob", "note": "再评估"},
    )
    await client.patch(f"/api/v1/strategies/{strategy_id}", json={"name": "v2"})
    archived = await client.post(f"/api/v1/strategies/{strategy_id}/archive")

    transitions = archived.json()["transitions"]
    assert len(transitions) == 3
    assert [item["from_status"] for item in transitions] == [
        "draft",
        "pending_approval",
        "rejected",
    ]
    assert [item["to_status"] for item in transitions] == [
        "pending_approval",
        "rejected",
        "archived",
    ]
    assert [item["at"] for item in transitions] == sorted(item["at"] for item in transitions)
    for item in transitions:
        assert item["actor"]
        assert item["request_id"]
    assert transitions[1]["reason"] == "再评估"

    rows = (
        await session.execute(
            select(StrategyTransition)
            .where(StrategyTransition.strategy_id == strategy_id)
            .order_by(StrategyTransition.at.asc(), StrategyTransition.id.asc())
        )
    ).scalars()
    stored = [
        {
            "from_status": row.from_status,
            "to_status": row.to_status,
            "actor": row.actor,
            "reason": row.reason,
            "request_id": row.request_id,
        }
        for row in rows
    ]
    assert stored == [
        {
            "from_status": item["from_status"],
            "to_status": item["to_status"],
            "actor": item["actor"],
            "reason": item["reason"],
            "request_id": item["request_id"],
        }
        for item in transitions
    ]


async def test_repeat_approve_is_rejected_without_extra_approval_row(client, session) -> None:
    target = await _seed_target(session)
    strategy_id = (await _create(client, target.id)).json()["id"]
    await client.post(f"/api/v1/strategies/{strategy_id}/submit")
    await client.post(f"/api/v1/strategies/{strategy_id}/approve", json={"reviewer": "alice"})

    again = await client.post(
        f"/api/v1/strategies/{strategy_id}/approve", json={"reviewer": "alice"}
    )

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "strategy_illegal_transition"
    approvals = (await client.get(f"/api/v1/strategies/{strategy_id}/approvals")).json()
    assert len(approvals["items"]) == 1


async def test_list_filters_pagination_and_latest_reviewer(client, session) -> None:
    target = await _seed_target(session)
    first = (await _create(client, target.id, params={"max_position_weight": 0.6})).json()
    second = (await _create(client, target.id, params={"max_position_weight": 0.59})).json()
    third = (await _create(client, target.id, params={"max_position_weight": 0.58})).json()
    await client.post(f"/api/v1/strategies/{second['id']}/submit")
    await client.post(f"/api/v1/strategies/{second['id']}/approve", json={"reviewer": "alice"})

    approved = (await client.get("/api/v1/strategies", params={"status": "approved"})).json()
    assert [item["id"] for item in approved["items"]] == [second["id"]]
    assert approved["items"][0]["reviewer"] == "alice"

    drafts = (await client.get("/api/v1/strategies", params={"status": "draft"})).json()
    assert {item["id"] for item in drafts["items"]} == {first["id"], third["id"]}

    page = (await client.get("/api/v1/strategies", params={"limit": 2})).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    rest = (
        await client.get("/api/v1/strategies", params={"limit": 2, "cursor": page["next_cursor"]})
    ).json()
    assert [item["id"] for item in rest["items"]] == [first["id"]]
    assert all(len(item["legs"]) == 2 for item in page["items"])

    invalid = await client.get("/api/v1/strategies", params={"cursor": "abc"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_CURSOR"


async def test_missing_source_and_unknown_names_use_envelope_codes(client, session) -> None:
    missing_target = await _create(client, 999999)
    assert missing_target.status_code == 404
    assert missing_target.json()["error"]["code"] == "TARGET_NOT_FOUND"

    missing_opportunity = await _create(client, None, params={"opportunity_id": 999999})
    assert missing_opportunity.status_code == 404
    assert missing_opportunity.json()["error"]["code"] == "OPPORTUNITY_NOT_FOUND"

    target = await _seed_target(session)
    unknown = await _create(client, target.id, templates=["no_such_template"])
    assert unknown.status_code == 422
    error = unknown.json()["error"]
    assert error["code"] == "strategy_unknown_template"
    assert error["message"]
    assert "request_id" in error

    no_source = await _create(client, None)
    assert no_source.status_code == 422
    assert no_source.json()["error"]["code"] == "strategy_source_required"


async def test_opportunity_source_builds_pair_with_run_provenance(client, session) -> None:
    run_id, opportunity_id = await _seed_opportunity(session)

    response = await _create(client, None, params={"opportunity_id": opportunity_id})

    assert response.status_code == 201
    body = response.json()
    assert body["source"]["type"] == "opportunity"
    assert body["source"]["run_id"] == run_id
    assert body["source"]["opportunity_id"] == opportunity_id
    assert len(body["legs"]) == 2
    assert {leg["side"] for leg in body["legs"]} == {"long", "short"}
    assert sum(abs(Decimal(leg["weight"])) for leg in body["legs"]) == Decimal("1.0000000000")


async def test_target_without_instrument_or_data_is_rejected_with_reason(client, session) -> None:
    bare = TargetSymbol(symbol="ZZZ", exchange="XNAS")
    session.add(bare)
    await session.commit()

    response = await _create(client, bare.id)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "strategy_no_source_data"


async def test_missing_market_snapshot_is_excluded_not_fabricated(client, session) -> None:
    anchor = await insert_instrument(session, "AAPL-USDT-SWAP")
    peer = await insert_instrument(session, "MSFT-USDT-SWAP")
    target = TargetSymbol(symbol="AAPL", exchange="XNAS", instrument_id=anchor.id)
    session.add(target)
    await session.flush()
    snapshot = RelationSnapshot(
        target_id=target.id,
        as_of=NOW,
        window_bars=60,
        method="pearson",
        price_basis="okx_close",
        lag_max=5,
        sample_size=60,
        run_key="relations-bare",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        RelationEdge(
            snapshot_id=snapshot.id,
            counterparty_id=peer.id,
            coefficient=Decimal("0.9"),
            best_lag=0,
            rank=1,
        )
    )
    # 只落锚点截面，对手方没有行情快照。
    session.add(
        MarketSnapshot(
            as_of=NOW,
            instrument_id=anchor.id,
            ret_5d=Decimal("0.02"),
            ret_20d=Decimal("0.05"),
            vol_20d=Decimal("0.02"),
        )
    )
    await session.commit()

    response = await _create(client, target.id)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "strategy_no_source_data"
    exclusions = body["error"]["details"]["exclusions"]
    assert exclusions and exclusions[0]["instrument_id"] == peer.id
    assert "missing market snapshot" in exclusions[0]["reason"]


async def test_patch_legs_replaces_content_and_bumps_version(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]
    legs = created["legs"]

    response = await client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "legs": [
                {
                    "instrument_id": legs[0]["instrument_id"],
                    "side": "long",
                    "target_weight": "0.4",
                    "rationale": "manual: coefficient=0.87 / window=60",
                    "rank": 1,
                },
                {
                    "instrument_id": legs[1]["instrument_id"],
                    "side": "short",
                    "target_weight": "-0.6",
                    "rationale": "manual: coefficient=0.87 / window=60",
                    "rank": 2,
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == created["version"] + 1
    assert body["content_hash"] != created["content_hash"]
    assert [leg["weight"] for leg in body["legs"]] == ["0.4000000000", "-0.6000000000"]
    assert sum(abs(Decimal(leg["weight"])) for leg in body["legs"]) == Decimal("1.0000000000")


async def test_patch_tightened_limits_revalidate_existing_legs(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]

    response = await client.patch(
        f"/api/v1/strategies/{strategy_id}", json={"params": {"max_position_weight": 0.3}}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "strategy_position_limit"

    unchanged = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()
    assert unchanged["content_hash"] == created["content_hash"]
    assert unchanged["version"] == created["version"]
    assert unchanged["params"]["limits"]["max_position_weight"] == 0.6
    assert [leg["weight"] for leg in unchanged["legs"]] == [
        leg["weight"] for leg in created["legs"]
    ]


async def test_patch_legs_with_unknown_instrument_is_a_domain_error(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]

    response = await client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "legs": [
                {
                    "instrument_id": 1_000_000,
                    "side": "long",
                    "target_weight": "0.5",
                    "rationale": "manual: coefficient=0.9 / window=60",
                },
                {
                    "instrument_id": created["legs"][1]["instrument_id"],
                    "side": "short",
                    "target_weight": "-0.5",
                    "rationale": "manual: coefficient=0.9 / window=60",
                },
            ]
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "strategy_instrument_not_found"
    assert error["details"]["instrument_ids"] == [1_000_000]
    assert error["request_id"]

    unchanged = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()
    assert [leg["instrument_id"] for leg in unchanged["legs"]] == [
        leg["instrument_id"] for leg in created["legs"]
    ]


async def test_patch_legs_rejects_duplicates_and_side_mismatch(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]
    instrument_id = created["legs"][0]["instrument_id"]

    duplicate = await client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "legs": [
                {
                    "instrument_id": instrument_id,
                    "side": "long",
                    "target_weight": "0.5",
                    "rationale": "manual: coefficient=0.9 / window=60",
                },
                {
                    "instrument_id": instrument_id,
                    "side": "short",
                    "target_weight": "-0.5",
                    "rationale": "manual: coefficient=0.9 / window=60",
                },
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "strategy_duplicate_leg"

    mismatch = await client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "legs": [
                {
                    "instrument_id": instrument_id,
                    "side": "long",
                    "target_weight": "-0.5",
                    "rationale": "manual: coefficient=0.9 / window=60",
                },
                {
                    "instrument_id": created["legs"][1]["instrument_id"],
                    "side": "short",
                    "target_weight": "0.5",
                    "rationale": "manual: coefficient=0.9 / window=60",
                },
            ]
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "strategy_side_weight_mismatch"


async def test_patch_rejects_reserved_provenance_params(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]

    response = await client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={"params": {"source": {"type": "opportunity"}, "opportunity_id": 7}},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "strategy_reserved_param"
    assert error["details"]["keys"] == ["opportunity_id", "source"]


async def test_candidates_beyond_max_legs_are_excluded_with_reason(client, session) -> None:
    members = []
    for index in range(8):
        instrument = await insert_instrument(session, f"SYM{index}-USDT-SWAP")
        members.append(
            {
                "instrument_id": instrument.id,
                "inst_id": f"SYM{index}-USDT-SWAP",
                "symbol": f"SYM{index}",
                "ret_5d": 0.01 * (index + 1),
                "vol_20d": 0.02,
            }
        )
    run = OpportunityRun(run_key="run-many", as_of=NOW, universe_size=8, status="ok")
    session.add(run)
    await session.flush()
    row = Opportunity(
        run_id=run.id,
        kind="directional",
        primary_instrument_id=members[0]["instrument_id"],
        direction="long",
        score=Decimal("1.5"),
        horizon="swing",
        reasons=["breadth expanding"],
        evidence={"cluster": "c9", "members": members},
        dedupe_key="d9",
    )
    session.add(row)
    await session.commit()

    response = await _create(
        client,
        target_id=None,
        kind="directional",
        templates=["momentum"],
        params={"opportunity_id": row.id},
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["legs"]) == 6
    dropped = [item for item in body["exclusions"] if "max_legs" in item["reason"]]
    assert len(dropped) == 2


async def test_patch_converging_to_existing_content_is_a_conflict(client, session) -> None:
    target = await _seed_target(session)
    first = (await _create(client, target.id, params={"max_position_weight": 0.6})).json()
    second = (await _create(client, target.id, params={"max_position_weight": 0.55})).json()
    assert first["strategy_key"] != second["strategy_key"]

    response = await client.patch(
        f"/api/v1/strategies/{second['id']}", json={"params": {"max_position_weight": 0.6}}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "strategy_key_conflict"
    assert error["details"]["existing_id"] == first["id"]
    assert error["request_id"]

    unchanged = (await client.get(f"/api/v1/strategies/{second['id']}")).json()
    assert unchanged["strategy_key"] == second["strategy_key"]
    assert unchanged["version"] == second["version"]


async def test_concurrent_terminal_decisions_are_serialized(client, session) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]
    assert (await client.post(f"/api/v1/strategies/{strategy_id}/submit")).status_code == 200

    async def decide(action: str, reviewer: str) -> str:
        async with session_factory() as other:
            try:
                await service.transition(
                    other,
                    strategy_id,
                    action,
                    actor=reviewer,
                    note="concurrent",
                    request_id=f"req-{reviewer}",
                )
                return "ok"
            except ConstraintViolation as exc:
                await other.rollback()
                return exc.code

    results = await asyncio.gather(
        decide("approve", "appr-A"),
        decide("reject", "rej-B"),
    )

    assert sorted(results) == ["ok", "strategy_illegal_transition"]

    detail = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()
    assert detail["status"] in {"approved", "rejected"}
    assert len(detail["approvals"]) == 1
    assert detail["approvals"][0]["decision"] == detail["status"]
    terminal = [item for item in detail["transitions"] if item["from_status"] == "pending_approval"]
    assert len(terminal) == 1
    assert terminal[0]["to_status"] == detail["status"]
    assert (detail["approved_at"] is not None) == (detail["status"] == "approved")
