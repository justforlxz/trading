"""审批端点：四个推进动作、推进记录列表，以及非法转移与缺达标依据时的响应。

断言只看「请求得到什么状态、库里与响应里的阶段是什么」：阶段推进的记录由
`tests/strategy/test_approval.py` 逐条钉住，这里验证端点把请求接到状态机上、把域异常
翻成 400。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.instrument import sync_instruments
from app.strategy import (
    InstanceRecord,
    StrategyInstanceRow,
    ValidationGate,
    ValidationReport,
    advance,
    get_instance,
)
from tests.factories.instruments import make_ref
from tests.factories.strategies import make_instance

ACTOR = "lxz"


@pytest.fixture()
def instance(client: TestClient) -> InstanceRecord:
    """一支草稿阶段的实例；标的与参数走真实写入路径建出来。"""

    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    return make_instance(
        name="BTC/ETH 配对",
        inst_ids=["BTC-USDT", "ETH-USDT"],
    )


def passing_report() -> ValidationReport:
    """一份达标报告：回撤不超过上限、夏普不低于下限。"""

    return ValidationReport(
        report_id="br_20261112",
        gates=(
            ValidationGate("max_drawdown", maximum=Decimal("0.2")),
            ValidationGate("sharpe", minimum=Decimal("1")),
        ),
        metrics={"max_drawdown": Decimal("0.1"), "sharpe": Decimal("1.5")},
    )


def read_instance(instance_id: str) -> InstanceRecord:
    record = get_instance(instance_id)
    assert record is not None
    return record


def stage_of(instance_id: str) -> str:
    return read_instance(instance_id).lifecycle_status


def approvals(client: TestClient) -> dict[str, object]:
    response = client.get("/api/approvals")
    assert response.status_code == 200, response.text
    return response.json()


def test_submit_review_moves_the_instance_into_pending_review(
    client: TestClient, instance: InstanceRecord
) -> None:
    """提交审核：实例进待审核，同时写一条带推进人的记录。"""

    instance_id = instance.instance_id
    response = client.post(
        "/api/approvals",
        json={"instance_id": instance_id, "actor": ACTOR, "note": "提交人工审核"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["from_status"] == "strategy_generation"
    assert body["to_status"] == "pending_review"
    assert body["actor"] == ACTOR
    assert body["note"] == "提交人工审核"
    assert body["evidence"] is None
    assert stage_of(instance_id) == "pending_review"

    listed = approvals(client)
    assert listed["total"] == 1
    assert [item["approval_id"] for item in listed["items"]] == [body["approval_id"]]


def test_approve_records_the_reviewer_and_moves_to_backtested(
    client: TestClient, instance: InstanceRecord
) -> None:
    """审核通过：进历史回测阶段，记录里留下审核人与依据引用。"""

    instance_id = instance.instance_id
    client.post("/api/approvals", json={"instance_id": instance_id, "actor": ACTOR})

    response = client.post(
        f"/api/approvals/{instance_id}/approve",
        json={"actor": "reviewer", "evidence": "pr_20261112", "note": "结论可复现"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["from_status"], body["to_status"]) == ("pending_review", "backtested")
    assert body["actor"] == "reviewer"
    assert body["evidence"] == "pr_20261112"
    assert stage_of(instance_id) == "backtested"

    assert read_instance(instance_id).approved_by == "reviewer"


def test_reject_sends_the_instance_back_to_the_draft_only(
    client: TestClient, instance: InstanceRecord
) -> None:
    """驳回：实例进 rejected；从 rejected 不能直接申请实盘授权。"""

    instance_id = instance.instance_id
    client.post("/api/approvals", json={"instance_id": instance_id, "actor": ACTOR})

    rejected = client.post(
        f"/api/approvals/{instance_id}/reject", json={"actor": ACTOR, "note": "回撤太大"}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["to_status"] == "rejected"
    assert stage_of(instance_id) == "rejected"

    blocked = client.post(
        f"/api/approvals/{instance_id}/live-authorization",
        json={"actor": ACTOR, "capital_budget": "2000.00"},
    )
    assert blocked.status_code == 400, blocked.text


def test_illegal_transition_answers_400_and_changes_nothing(
    client: TestClient, instance: InstanceRecord
) -> None:
    """草稿阶段直接审核通过不在转移表里：400，实例仍停在草稿。"""

    instance_id = instance.instance_id
    response = client.post(f"/api/approvals/{instance_id}/approve", json={"actor": ACTOR})

    assert response.status_code == 400, response.text
    assert "pending_review" in response.json()["detail"]
    assert stage_of(instance_id) == "strategy_generation"
    assert approvals(client)["total"] == 0


def test_live_authorization_records_the_fact_and_checks_the_budget(
    client: TestClient, instance: InstanceRecord
) -> None:
    """实盘授权：模拟交易阶段之后才可申请，预算必须为正数。

    `validated` 与 `paper_trading` 没有端点（契约里没有这两个动作），这两步用域函数推进，
    端点只负责最后那一步。
    """

    instance_id = instance.instance_id
    client.post("/api/approvals", json={"instance_id": instance_id, "actor": ACTOR})
    client.post(f"/api/approvals/{instance_id}/approve", json={"actor": ACTOR})
    advance(read_instance(instance_id), "validated", ACTOR, passing_report())
    advance(read_instance(instance_id), "paper_trading", ACTOR)

    refused = client.post(
        f"/api/approvals/{instance_id}/live-authorization",
        json={"actor": ACTOR, "capital_budget": "0"},
    )
    assert refused.status_code == 400, refused.text

    authorized = client.post(
        f"/api/approvals/{instance_id}/live-authorization",
        json={"actor": ACTOR, "capital_budget": "2000.00", "note": "先小仓位"},
    )
    assert authorized.status_code == 200, authorized.text
    body = authorized.json()
    assert (body["from_status"], body["to_status"]) == ("paper_trading", "live_authorized")
    assert stage_of(instance_id) == "live_authorized"

    assert read_instance(instance_id).live_authorized_at is not None


def test_unknown_instance_answers_404(client: TestClient) -> None:
    """实例不存在时四个动作都回 404，而不是把状态机错误当成 400 报出来。"""

    for path, payload in (
        ("/api/approvals/si_missing/approve", {"actor": ACTOR}),
        ("/api/approvals/si_missing/reject", {"actor": ACTOR}),
        (
            "/api/approvals/si_missing/live-authorization",
            {"actor": ACTOR, "capital_budget": "2000.00"},
        ),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 404, (path, response.text)

    submitted = client.post("/api/approvals", json={"instance_id": "si_missing", "actor": ACTOR})
    assert submitted.status_code == 404, submitted.text


def test_instance_rows_keep_the_column_the_screen_reads(
    client: TestClient, instance: InstanceRecord
) -> None:
    """写库的列名是 `lifecycle_status`；对外的 `status` 字段由接口层映射出来。"""

    with session_scope() as session:
        row = session.get(StrategyInstanceRow, instance.instance_id)
        assert row is not None
        assert row.lifecycle_status == "strategy_generation"
        assert "status" not in StrategyInstanceRow.__table__.columns
