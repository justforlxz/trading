"""研究记录端点：创建、反查、更新、删除与关联校验。

关联对象都先走真实业务写入路径（标的同步、日线落库、策略与回测创建），再创建
记录并通过筛选反查；断言只针对请求与库里能复算的值。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import Bar, Timeframe
from app.instrument import sync_instruments
from app.market import upsert_candles
from tests.factories.instruments import make_ref
from tests.factories.strategies import make_strategy

DAY = timedelta(days=1)
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
PAIR_PARAMS = {"reversion_window": 3, "strength_window": 2, "pair_count": 1}


def _seed_backtest(client: TestClient) -> tuple[str, str, str]:
    """建两只加密现货、一个策略版本与一次回测；返回策略、版本与回测标识。"""

    inst_ids = ["BTC-USDT", "ETH-USDT"]
    sync_instruments(
        [
            make_ref(inst_id=inst_id, base_ccy=inst_id.split("-")[0], inst_category="1")
            for inst_id in inst_ids
        ]
    )
    closes = {
        "BTC-USDT": ["100", "101", "102", "103", "104", "105"],
        "ETH-USDT": ["50", "51", "52", "53", "55", "58"],
    }
    for inst_id, values in closes.items():
        opens = [AS_OF - DAY * (len(values) - 1 - index) for index in range(len(values))]
        upsert_candles(
            [
                Bar(
                    inst_id=inst_id,
                    timeframe=Timeframe.parse("1d"),
                    open_time=open_time,
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=Decimal("10"),
                    confirm=True,
                    source="okx_spot",
                )
                for open_time, close in zip(opens, values, strict=True)
            ]
        )

    strategy = make_strategy(
        name="BTC/ETH 研究记录",
        category="relative_value",
        direction="long_short",
        params=PAIR_PARAMS,
        inst_ids=inst_ids,
    )
    created = client.post(
        "/api/backtests",
        json={
            "strategy_version_id": strategy.current_version_id,
            "targets": {"mode": "single", "inst_ids": ["BTC-USDT"], "group": None},
            "bar": "1d",
            "start_date": "2026-11-05",
            "end_date": "2026-11-10",
            "initial_capital": "10000",
            "quote_currency": "USDT",
            "position_size": "10000",
            "max_position_pct": "1",
            "costs": {
                "maker_fee_bps": "2",
                "taker_fee_bps": "10",
                "slippage_bps": "5",
                "spread_bps": "2",
            },
            "funding_enabled": True,
            "execution_model": "next_open",
            "data_source": "okx_spot",
        },
    )
    assert created.status_code == 202, created.text
    return strategy.id, strategy.current_version_id, created.json()["run_id"]


def _create_note(client: TestClient, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "type": "hypothesis",
        "title": "BTC 相对 ETH 走强",
        "content": "价差回到均值后做多 BTC、做空 ETH，观察三日。",
        "tags": ["相对价值", "验证中"],
    }
    body.update(overrides)
    response = client.post("/api/research-notes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_note_links_backtest_and_can_be_found_by_link(client: TestClient) -> None:
    """创建假设记录并关联回测后，能从记录列表按回测标识反查到它。"""

    strategy_id, _, run_id = _seed_backtest(client)
    created = _create_note(
        client,
        related_instrument_id="BTC-USDT",
        related_strategy_id=strategy_id,
        related_backtest_id=run_id,
    )

    assert created["type"] == "hypothesis"
    assert created["title"] == "BTC 相对 ETH 走强"

    listing = client.get("/api/research-notes", params={"related_backtest_id": run_id}).json()[
        "items"
    ]
    assert [item["id"] for item in listing] == [created["id"]]
    assert listing[0]["related_instrument_id"] == "BTC-USDT"
    assert listing[0]["related_strategy_id"] == strategy_id
    assert listing[0]["related_backtest_id"] == run_id
    assert listing[0]["tags"] == ["相对价值", "验证中"]

    detail = client.get(f"/api/research-notes/{created['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json() == listing[0]

    by_strategy = client.get(
        "/api/research-notes", params={"related_strategy_id": strategy_id}
    ).json()["items"]
    assert [item["id"] for item in by_strategy] == [created["id"]]


def test_update_changes_fields_and_writes_activity(client: TestClient) -> None:
    """更新标题、标签与关联对象；状态变化来自服务端的活动流水。"""

    _, _, run_id = _seed_backtest(client)
    created = _create_note(client, related_backtest_id=run_id)

    updated = client.put(
        f"/api/research-notes/{created['id']}",
        json={"title": "更新后的标题", "tags": ["已复核"], "related_backtest_id": None},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "更新后的标题"
    assert "updated_at" in updated.json()

    detail = client.get(f"/api/research-notes/{created['id']}").json()
    assert detail["tags"] == ["已复核"]
    assert detail["related_backtest_id"] is None

    activity = client.get("/api/activity", params={"event_type": "research_note.updated"}).json()[
        "items"
    ]
    assert [item["object_id"] for item in activity] == [created["id"]]


def test_delete_note_is_204_and_then_404(client: TestClient) -> None:
    """删除不存在的记录返回 404；删除成功后详情也返回 404。"""

    created = _create_note(client)

    first = client.delete(f"/api/research-notes/{created['id']}")
    second = client.delete(f"/api/research-notes/{created['id']}")

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 404
    assert client.get(f"/api/research-notes/{created['id']}").status_code == 404


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("related_instrument_id", "NOPE-USDT"),
        ("related_strategy_id", "st_missing"),
        ("related_backtest_id", "bt_missing"),
    ],
)
def test_unknown_link_is_404(client: TestClient, field: str, value: str) -> None:
    """关联标的、策略或回测不存在时拒绝创建，不写半条记录。"""

    response = client.post(
        "/api/research-notes",
        json={
            "type": "decision",
            "title": "关联校验",
            "content": "引用不存在的对象。",
            field: value,
        },
    )

    assert response.status_code == 404, response.text
    assert client.get("/api/research-notes").json()["items"] == []


def test_blank_title_is_400(client: TestClient) -> None:
    """标题为空属于调用方参数错误，不落库。"""

    response = client.post(
        "/api/research-notes",
        json={"type": "review", "title": "   ", "content": "内容"},
    )

    assert response.status_code == 400
    assert client.get("/api/research-notes").json()["items"] == []


def test_backtest_start_and_failure_append_activity(client: TestClient) -> None:
    """回测开始与失败都由服务端写活动；失败的活动带出错误原因。"""

    _, version_id, run_id = _seed_backtest(client)

    started = client.get("/api/activity", params={"event_type": "backtest.started"}).json()["items"]
    completed = client.get("/api/activity", params={"event_type": "backtest.completed"}).json()[
        "items"
    ]
    assert [item["object_id"] for item in started] == [version_id]
    assert [item["object_id"] for item in completed] == [run_id]

    failed = client.post(
        "/api/backtests",
        json={
            "strategy_version_id": "sv_missing",
            "targets": {"mode": "single", "inst_ids": ["BTC-USDT"], "group": None},
            "bar": "1d",
            "start_date": "2026-11-05",
            "end_date": "2026-11-10",
            "initial_capital": "10000",
            "quote_currency": "USDT",
            "position_size": "10000",
            "max_position_pct": "1",
            "costs": {
                "maker_fee_bps": "2",
                "taker_fee_bps": "10",
                "slippage_bps": "5",
                "spread_bps": "2",
            },
            "funding_enabled": True,
            "execution_model": "next_open",
            "data_source": "okx_spot",
        },
    )
    assert failed.status_code == 404

    failures = client.get("/api/activity", params={"event_type": "backtest.failed"}).json()["items"]
    assert [item["object_id"] for item in failures] == ["sv_missing"]
    assert "sv_missing" in failures[0]["payload"]["error"]
