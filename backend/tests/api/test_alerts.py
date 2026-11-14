"""提醒与活动端点：扫描去重、确认/忽略、条件恢复与活动分页。

提醒只由 `GET /api/alerts` 的默认查询触发扫描；首页只读提醒表。测试里的每条提醒
都来自真实持仓风险规则，不手写响应形状。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.alerts import AlertEventRow, scan_alerts, update_alert_status
from app.core import Conflict
from app.db import session_scope


def _open_position(client: TestClient, key: str = "alert-1") -> dict[str, object]:
    response = client.post(
        "/api/manual-positions",
        json={
            "inst_id": "AAPL-USDT-SWAP",
            "side": "long",
            "quantity": "2",
            "avg_cost": "55",
            "leverage": "2",
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _alert_count() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(AlertEventRow)) or 0)


def test_repeated_scan_of_same_bar_keeps_one_alert_per_rule(
    market_data: TestClient,
) -> None:
    """同一标的、同一规则、同一 bar 连续扫描两次只产生一条提醒。"""

    _open_position(market_data)

    first = market_data.get("/api/alerts")
    second = market_data.get("/api/alerts")

    assert first.status_code == 200, first.text
    first_items = first.json()["items"]
    second_items = second.json()["items"]
    assert {item["rule_id"] for item in first_items} == {
        "single_instrument_weight",
        "stop_missing",
    }
    assert [item["id"] for item in first_items] == [item["id"] for item in second_items]
    assert _alert_count() == len(first_items)

    with session_scope() as session:
        keys = list(session.scalars(select(AlertEventRow.dedup_key)))
    assert len(keys) == len(set(keys))


def test_acknowledged_alert_leaves_pending_and_writes_activity(
    market_data: TestClient,
) -> None:
    """确认后状态变为 acknowledged，重复处置返回 409，活动流水新增一条。"""

    _open_position(market_data)
    pending = market_data.get("/api/alerts").json()["items"]
    alert = next(item for item in pending if item["rule_id"] == "stop_missing")

    confirmed = market_data.patch(f"/api/alerts/{alert['id']}", json={"status": "acknowledged"})
    repeated = market_data.patch(f"/api/alerts/{alert['id']}", json={"status": "ignored"})

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "acknowledged"
    assert repeated.status_code == 409

    still_pending = market_data.get("/api/alerts").json()["items"]
    assert alert["id"] not in {item["id"] for item in still_pending}
    acknowledged = market_data.get("/api/alerts", params={"status": "acknowledged"}).json()["items"]
    assert [item["id"] for item in acknowledged] == [alert["id"]]

    activity = market_data.get("/api/activity", params={"event_type": "alert.acknowledged"}).json()[
        "items"
    ]
    assert [item["object_id"] for item in activity] == [alert["id"]]
    assert activity[0]["payload"]["rule_id"] == "stop_missing"


def test_adding_stop_expires_the_stop_missing_alert(
    market_data: TestClient,
) -> None:
    """条件恢复时旧提醒标记为 expired，不删除；状态变化写入活动。"""

    position = _open_position(market_data)
    pending = market_data.get("/api/alerts").json()["items"]
    alert = next(item for item in pending if item["rule_id"] == "stop_missing")

    updated = market_data.patch(f"/api/manual-positions/{position['id']}", json={"stop_px": "50"})
    assert updated.status_code == 200, updated.text

    market_data.get("/api/alerts")

    expired = market_data.get("/api/alerts", params={"status": "expired"}).json()["items"]
    assert [item["id"] for item in expired] == [alert["id"]]
    assert expired[0]["status"] == "expired"
    assert expired[0]["expires_at"] is not None

    activity = market_data.get("/api/activity", params={"event_type": "alert.expired"}).json()[
        "items"
    ]
    assert [item["object_id"] for item in activity] == [alert["id"]]
    assert activity[0]["payload"]["previous_status"] == "pending"


def test_activity_is_filtered_and_paginated_by_cursor(market_data: TestClient) -> None:
    """活动按时间倒序返回；同秒内多行也能用游标稳定翻页。"""

    market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})
    market_data.patch("/api/watchlist/XAAPL-USDT", json={"group": "观察"})

    first = market_data.get("/api/activity", params={"limit": 1})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is not None

    second = market_data.get(
        "/api/activity", params={"limit": 1, "cursor": body["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] != body["items"][0]["id"]
    assert second["items"][0]["created_at"] <= body["items"][0]["created_at"]

    moved = market_data.get("/api/activity", params={"event_type": "watchlist.item.moved"}).json()[
        "items"
    ]
    assert [item["event_type"] for item in moved] == ["watchlist.item.moved"]


def test_concurrent_scans_keep_one_alert_per_rule(market_data: TestClient) -> None:
    """两个扫描同时落库时，唯一约束由数据库兜住，不抛 500。"""

    _open_position(market_data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in [pool.submit(scan_alerts) for _ in range(2)]]

    assert _alert_count() == 2
    assert sum(outcome.created for outcome in outcomes) == 2
    with session_scope() as session:
        keys = list(session.scalars(select(AlertEventRow.dedup_key)))
    assert len(keys) == len(set(keys))


def test_concurrent_status_update_only_one_wins(market_data: TestClient) -> None:
    """并发处置同一条提醒时，行锁让后到的请求读到新状态并返回冲突。"""

    _open_position(market_data)
    items = market_data.get("/api/alerts").json()["items"]
    alert = next(item for item in items if item["rule_id"] == "stop_missing")

    def confirm() -> str:
        try:
            record = update_alert_status(alert["id"], "acknowledged")
        except Conflict:
            return "conflict"
        return "missing" if record is None else record.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in [pool.submit(confirm) for _ in range(2)]]

    assert sorted(outcomes) == ["acknowledged", "conflict"]
    activity = market_data.get("/api/activity", params={"event_type": "alert.acknowledged"}).json()[
        "items"
    ]
    assert [item["object_id"] for item in activity] == [alert["id"]]


def test_naive_activity_time_range_is_rejected(market_data: TestClient) -> None:
    """不带时区的 `from`/`to` 在请求校验阶段返回 422，而不是 500。"""

    assert market_data.get("/api/activity", params={"from": "2026-11-01"}).status_code == 422
    assert market_data.get("/api/activity", params={"to": "2026-11-10"}).status_code == 422
