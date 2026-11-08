"""P4-06: 未配置 fail-closed、动作安全检查、只读许可与审计记录。

判定规则见 `app/ai/core/query.py`: 动作安全检查 → 正向读取许可 → 域端口调用。
命中受控对象类别的祈使句返回 403 `ai_write_forbidden`; 其余祈使句、无法判断的输入
和未许可的疑问句返回 200 且 `answerable=false`, 且都不带任何域数据。
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ai.conftest import seed_full_backtest

ENDPOINTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("/api/v1/ai/explain/market", {}),
    ("/api/v1/ai/explain/relations", {"target_id": 1}),
    ("/api/v1/ai/explain/strategy", {"strategy_id": 1}),
    ("/api/v1/ai/explain/backtest", {"run_id": 1}),
    ("/api/v1/ai/query", {"question": "解释一下当前行情"}),
    ("/api/v1/ai/suggest/strategy", {"target_id": 1}),
)


class NoExternalCalls:
    """任何属性访问都炸: 用来证明未配置时根本没有走到外部模型。"""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"external adapter touched: {name}")


async def test_unconfigured_endpoints_all_return_503_without_external_calls(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai import service as ai_service

    # 死端口 + provider=none: 即使填了地址也不允许发起任何外部请求。
    configure_ai(enabled=True, provider="none", base_url="http://127.0.0.1:9")
    monkeypatch.setattr(ai_service, "build_adapter", lambda config: NoExternalCalls())

    for path, body in ENDPOINTS:
        response = await client.post(path, json=body)
        assert response.status_code == 503, (path, response.text)
        error = response.json()["error"]
        assert error["code"] == "ai_not_configured"
        assert error["request_id"]

    from app.ops.models import AuditLog

    count = await session.scalar(select(func.count()).select_from(AuditLog))
    assert count == 0


async def test_disabled_flag_also_returns_503(client: AsyncClient, configure_ai) -> None:
    configure_ai(enabled=False, provider="rule_based")
    response = await client.post("/api/v1/ai/explain/market", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


async def test_write_intent_is_forbidden_with_refusal_details(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    from app.ops.models import AuditLog

    configure_ai()

    response = await client.post(
        "/api/v1/ai/query",
        json={"question": "撤掉所有挂单"},
        headers={"X-Request-ID": "req-ai-write-1"},
    )
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "ai_write_forbidden"
    refusal = error["details"]["refusal"]
    assert refusal["code"] == "write_forbidden"
    assert refusal["matched_object_class"] == "trade"
    assert refusal["message"]

    rows = list(await session.scalars(select(AuditLog)))
    assert len(rows) == 1
    assert rows[0].actor == "ai"
    assert rows[0].action == "ai.query"
    assert rows[0].resource == "query"
    assert rows[0].after["outcome"] == "forbidden"


@pytest.mark.parametrize(
    "question",
    [
        # 句首处置前缀 + 受控对象: 403。
        "把策略 1 改成做空",
        "把风控敞口限制调低",
        "将策略 1 换成做多",
        "调低风控敞口",
        "把实盘打开",
        "把杠杆调到 3 倍",
        "把杠杆提高到 3 倍",
        "把仓位减到一半",
        "把策略\n改成做空",
        "开实盘",
        "把杠杆降下来",
        "把策略删了",
        "帮我把仓位砍一半",
        "给策略 1 加一条腿",
        "让实盘跑起来",
        "把资金全都投到 BTC",
        "清仓",
        # 句首不是处置前缀也不以动作词根开头: 200 且 answerable=false, 同样不给数据。
        "风控阈值调高到 0.2",
        "策略方向改为做空",
        "启动实盘",
        "风控阈值放低一点",
        "风控阈值\n改成 0.3",
        "策略方向\n改为做空",
        "approve strategy 1",
        "modify leg weight of strategy 1",
        # 命令 + 附加只读问法: 仍属于「不作答」。
        "止损改到 95,为什么",
        "策略 1 改成做空,顺便说明一下理由",
        "杠杆升到 5 倍,有什么风险",
        "策略 1 删除,解释后果",
        "实盘关掉,说明一下影响",
    ],
)
async def test_write_style_questions_never_answer_with_data(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
    question: str,
) -> None:
    from app.ops.models import AuditLog

    configure_ai()
    response = await client.post("/api/v1/ai/query", json={"question": question})

    expected_outcome = "forbidden"
    if response.status_code == 403:
        assert response.json()["error"]["code"] == "ai_write_forbidden"
    else:
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["answerable"] is False
        assert payload["citations"] == []
        assert payload["read_only"] is True
        expected_outcome = "refused"

    rows = list(await session.scalars(select(AuditLog)))
    assert len(rows) == 1
    assert rows[0].after["outcome"] == expected_outcome


async def test_overlong_question_maps_to_ai_invalid_request(
    client: AsyncClient, configure_ai
) -> None:
    """超长问题属于助手请求非法, 不能落到全局 VALIDATION_ERROR。"""

    configure_ai()
    response = await client.post("/api/v1/ai/query", json={"question": "问" * 2101})
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "ai_invalid_request"
    assert error["details"]["field"] == "question"


async def test_each_backtest_explanation_writes_one_audit_row(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    from app.ops.models import AuditLog

    seeded = await seed_full_backtest(session)
    configure_ai()

    response = await client.post(
        "/api/v1/ai/explain/backtest",
        json={"run_id": seeded.run_id},
        headers={"X-Request-ID": "req-ai-audit-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["answerable"] is True

    rows = list(await session.scalars(select(AuditLog)))
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == "ai"
    assert row.action == "ai.explain.backtest"
    assert row.resource == "backtest"
    assert row.resource_id == str(seeded.run_id)
    assert row.request_id == "req-ai-audit-1"
    assert row.after["outcome"] == "ok"
    assert row.after["model"] == {"provider": "rule_based", "model": "rules-v1"}
    assert isinstance(row.after["latency_ms"], int)
    assert row.idempotency_key is not None


async def test_same_request_id_does_not_duplicate_audit(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    from app.ops.models import AuditLog

    configure_ai()
    headers = {"X-Request-ID": "req-ai-idem-1"}

    first = await client.post("/api/v1/ai/explain/market", json={}, headers=headers)
    second = await client.post("/api/v1/ai/explain/market", json={}, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    count = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "ai.explain.market")
    )
    assert count == 1


async def test_read_only_question_answers_with_intent_and_citations(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    from app.ops.models import AuditLog

    seeded = await seed_full_backtest(session)
    configure_ai()

    response = await client.post(
        "/api/v1/ai/query", json={"question": f"解释回测 {seeded.run_id} 的表现"}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "backtest"
    assert payload["answer"]
    assert payload["answerable"] is True
    assert payload["read_only"] is True
    assert any(item["type"] == "backtest_metric" for item in payload["citations"])
    rows = list(await session.scalars(select(AuditLog)))
    assert [row.action for row in rows] == ["ai.query"]
    assert rows[0].after["outcome"] == "ok"


async def test_explicit_explain_endpoint_carries_read_only_flags(
    client: AsyncClient, session: AsyncSession, configure_ai
) -> None:
    configure_ai()
    response = await client.post("/api/v1/ai/explain/market", json={})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["answerable"] is True
