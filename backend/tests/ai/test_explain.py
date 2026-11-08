"""P4-02/03: 市场、关系、策略与回测解释的引用必须与既有 GET 接口逐项一致。"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ai.conftest import (
    DEFAULT_METRICS,
    seed_full_backtest,
    seed_relations,
    seed_target,
)

AS_OF = "2026-03-02T00:00:00+00:00"


def _by_type(payload: dict, kind: str) -> list[dict]:
    return [item for item in payload["citations"] if item["type"] == kind]


async def test_explain_market_citations_match_market_endpoints(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    apple = await seed_target(session, symbol="AAPL")
    msft = await seed_target(session, symbol="MSFT")
    configure_ai()

    # 日历由官方 GET 接口落库; 只读助手只读既有日历, 不再为查询写库。
    truth_sessions = await client.get(
        "/api/v1/market/sessions", params={"from": "2026-01-31", "to": "2026-03-02"}
    )
    assert truth_sessions.status_code == 200, truth_sessions.text

    response = await client.post("/api/v1/ai/explain/market", json={"as_of": AS_OF, "bar": "1d"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["model"] == {"provider": "rule_based", "model": "rules-v1"}
    assert payload["degraded"] is True
    assert payload["read_only"] is True
    assert payload["answerable"] is True
    assert payload["as_of"].startswith("2026-03-02")

    coverage_citations = _by_type(payload, "market_coverage")
    assert {item["instrument_id"] for item in coverage_citations} == {
        apple.inst_id,
        msft.inst_id,
    }
    for item in coverage_citations:
        truth = await client.get(
            "/api/v1/market/coverage",
            params={
                "inst_id": item["instrument_id"],
                "bar": "1d",
                "start": "2026-01-31T00:00:00+00:00",
                "end": AS_OF,
            },
        )
        assert truth.status_code == 200, truth.text
        summary = truth.json()["summary"]
        for field in ("expected", "actual", "missing", "ratio"):
            assert item[field] == summary[field], field

    session_citations = _by_type(payload, "market_session")
    assert session_citations
    expected = {
        (row["trading_date"], row["regular_start"], row["regular_end"])
        for row in truth_sessions.json()["items"]
    }
    cited = {
        (row["trading_date"], row["regular_start"], row["regular_end"]) for row in session_citations
    }
    assert cited == expected


async def test_explain_market_without_targets_reports_missing_data(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    del session
    configure_ai()
    response = await client.post("/api/v1/ai/explain/market", json={"as_of": AS_OF})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"].startswith("数据不足")
    assert "market_coverage" in payload["missing"]


async def test_explain_relations_citations_match_relations_endpoint(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    target = await seed_target(session, symbol="AAPL")
    snapshot_id = await seed_relations(session, target_id=target.target_id)
    configure_ai()

    response = await client.post(
        "/api/v1/ai/explain/relations", json={"target_id": target.target_id}
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    truth = await client.get(f"/api/v1/targets/{target.target_id}/relations")
    assert truth.status_code == 200, truth.text
    truth_payload = truth.json()
    assert truth_payload["snapshot"]["id"] == snapshot_id

    snapshots = _by_type(payload, "relation_snapshot")
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == truth_payload["snapshot"]["id"]
    assert snapshots[0]["as_of"] == truth_payload["snapshot"]["as_of"]
    assert snapshots[0]["window_bars"] == truth_payload["snapshot"]["window_bars"]

    cited_edges = {
        (row["instrument_id"], row["coefficient"], row["best_lag"])
        for row in _by_type(payload, "relation_edge")
    }
    truth_edges = {
        (row["counterparty_inst_id"], row["coefficient"], row["best_lag"])
        for row in truth_payload["edges"]
    }
    assert cited_edges == truth_edges
    assert all(
        row["snapshot_id"] == truth_payload["snapshot"]["id"]
        for row in _by_type(payload, "relation_edge")
    )


async def test_explain_relations_undefined_snapshot_is_not_invented(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    target = await seed_target(session, symbol="AAPL")
    configure_ai()
    response = await client.post(
        "/api/v1/ai/explain/relations", json={"target_id": target.target_id}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"].startswith("数据不足")
    assert payload["missing"] == ["relations_snapshot"]
    assert payload["citations"] == []


async def test_explain_relations_unknown_target_is_404(client: AsyncClient, configure_ai) -> None:
    configure_ai()
    response = await client.post("/api/v1/ai/explain/relations", json={"target_id": 999999})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ai_target_not_found"


async def test_explain_strategy_citations_match_strategy_endpoint(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    seeded = await seed_full_backtest(session)
    configure_ai()

    response = await client.post(
        "/api/v1/ai/explain/strategy", json={"strategy_id": seeded.strategy_id}
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    truth = await client.get(f"/api/v1/strategies/{seeded.strategy_id}")
    assert truth.status_code == 200, truth.text
    truth_payload = truth.json()

    strategy_citations = _by_type(payload, "strategy")
    assert len(strategy_citations) == 1
    assert strategy_citations[0]["strategy_id"] == seeded.strategy_id
    assert strategy_citations[0]["version"] == truth_payload["version"]

    cited_legs = {
        (row["inst_id"], row["side"], row["target_weight"])
        for row in _by_type(payload, "strategy_leg")
    }
    truth_legs = {(row["inst_id"], row["side"], row["weight"]) for row in truth_payload["legs"]}
    assert cited_legs == truth_legs


async def test_explain_backtest_metrics_match_metric_endpoint_exactly(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    seeded = await seed_full_backtest(session)
    configure_ai()

    response = await client.post("/api/v1/ai/explain/backtest", json={"run_id": seeded.run_id})
    assert response.status_code == 200, response.text
    payload = response.json()

    truth = await client.get(f"/api/v1/backtests/{seeded.run_id}/metrics")
    assert truth.status_code == 200, truth.text
    truth_items = {row["name"]: row["value"] for row in truth.json()["items"]}

    cited_items = {row["name"]: row["value"] for row in _by_type(payload, "backtest_metric")}
    assert cited_items == truth_items
    assert len(cited_items) == 10
    assert cited_items["total_return"] == DEFAULT_METRICS["total_return"]

    # 亏损回测: 结论只描述事实, 不得出现加仓/扩大仓位类建议。
    assert "亏损" in payload["summary"]
    for term in ("加仓", "扩大仓位", "加大仓位", "增加仓位", "提高仓位"):
        assert term not in payload["summary"]


async def test_explain_backtest_model_growth_advice_is_discarded(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
    use_fake_llm,
) -> None:
    seeded = await seed_full_backtest(session)
    configure_ai(
        provider="openai",
        model="fake-model",
        base_url="http://model.invalid/v1",
        api_key="key",
    )
    fake = use_fake_llm("该回测亏损, 建议加仓并扩大仓位以摊低成本。")

    response = await client.post("/api/v1/ai/explain/backtest", json={"run_id": seeded.run_id})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(fake.calls) == 1
    assert payload["degraded"] is True
    assert payload["model"] == {"provider": "rule_based", "model": "rules-v1"}
    assert "加仓" not in payload["summary"]
    assert "扩大仓位" not in payload["summary"]


async def test_explain_invalid_inputs_are_422_or_404(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
) -> None:
    seeded = await seed_full_backtest(session)
    configure_ai()

    invalid_bar = await client.post("/api/v1/ai/explain/market", json={"bar": "2h"})
    assert invalid_bar.status_code == 422
    assert invalid_bar.json()["error"]["code"] == "ai_invalid_request"

    unknown_run = await client.post("/api/v1/ai/explain/backtest", json={"run_id": 999999})
    assert unknown_run.status_code == 404
    assert unknown_run.json()["error"]["code"] == "ai_backtest_not_found"

    unknown_strategy = await client.post(
        "/api/v1/ai/explain/strategy", json={"strategy_id": 999999}
    )
    assert unknown_strategy.status_code == 404
    assert unknown_strategy.json()["error"]["code"] == "ai_strategy_not_found"

    assert seeded.run_id is not None
