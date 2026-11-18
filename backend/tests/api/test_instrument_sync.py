"""单标的按需同步接口：默认窗口、去重、冷却、周期隔离与错误路径。

后台任务用可控的假同步函数驱动，断言只看接口返回与调度器实际执行的调用，
不连真实 OKX。
"""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from app.jobs import OnDemandSyncScheduler
from tests.api.conftest import seed_instruments
from tests.factories.instruments import make_ref


def _wait_for_status(
    client: TestClient,
    inst_id: str,
    bar: str,
    expected: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.post(f"/api/instruments/{inst_id}/sync", json={"bar": bar})
        body = response.json()
        if body.get("status") == expected:
            return body
        time.sleep(0.01)
    raise AssertionError(f"等待状态 {expected} 超时, 实际 {body}")


def test_sync_defaults_to_daily_window_and_returns_202(client: TestClient) -> None:
    seed_instruments(make_ref())
    release = threading.Event()
    calls: list[tuple[str, str, int]] = []

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar, days))
        release.wait(5)

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    client.app.state.on_demand_sync = scheduler
    try:
        response = client.post("/api/instruments/XAAPL-USDT/sync", json={})

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["inst_id"] == "XAAPL-USDT"
        assert body["bar"] == "1d"
        assert body["days"] == 400
        assert body["status"] == "started"
        assert body["requested_at"].endswith("Z")
        deadline = time.monotonic() + 2
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert calls == [("XAAPL-USDT", "1d", 400)]
    finally:
        release.set()
        scheduler.shutdown()


def test_same_bar_running_then_fresh(client: TestClient) -> None:
    seed_instruments(make_ref())
    release = threading.Event()
    finished = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        release.wait(5)
        finished.set()

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    client.app.state.on_demand_sync = scheduler
    try:
        first = client.post("/api/instruments/XAAPL-USDT/sync", json={"bar": "1d"})
        assert first.json()["status"] == "started"
        second = client.post("/api/instruments/XAAPL-USDT/sync", json={"bar": "1d"})
        assert second.json()["status"] == "already_running"

        release.set()
        assert finished.wait(2)
        body = _wait_for_status(client, "XAAPL-USDT", "1d", "fresh")
        assert body["days"] == 400
    finally:
        release.set()
        scheduler.shutdown()


def test_switch_to_4h_runs_an_independent_task(client: TestClient) -> None:
    seed_instruments(make_ref())
    calls: list[tuple[str, str, int]] = []
    done = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar, days))
        if len(calls) == 2:
            done.set()

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=2)
    client.app.state.on_demand_sync = scheduler
    try:
        daily = client.post("/api/instruments/XAAPL-USDT/sync", json={"bar": "1d"})
        four_hour = client.post("/api/instruments/XAAPL-USDT/sync", json={"bar": "4h"})

        assert daily.json()["status"] == "started"
        assert four_hour.json()["status"] == "started"
        assert four_hour.json()["days"] == 90
        assert done.wait(2)
        assert sorted(calls) == [("XAAPL-USDT", "1d", 400), ("XAAPL-USDT", "4h", 90)]
    finally:
        scheduler.shutdown()


def test_explicit_days_are_used(client: TestClient) -> None:
    seed_instruments(make_ref())
    calls: list[tuple[str, str, int]] = []
    release = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar, days))
        release.wait(5)

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    client.app.state.on_demand_sync = scheduler
    try:
        response = client.post("/api/instruments/XAAPL-USDT/sync", json={"bar": "1h", "days": 7})

        assert response.status_code == 202, response.text
        assert response.json()["days"] == 7
        deadline = time.monotonic() + 2
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert calls == [("XAAPL-USDT", "1h", 7)]
    finally:
        release.set()
        scheduler.shutdown()


def test_upstream_failure_returns_backoff_not_500(client: TestClient) -> None:
    seed_instruments(make_ref())
    release = threading.Event()
    failed = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        release.wait(5)
        failed.set()
        raise RuntimeError("上游 429")

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    client.app.state.on_demand_sync = scheduler
    try:
        response = client.post("/api/instruments/XAAPL-USDT/sync", json={"bar": "1d"})
        assert response.status_code == 202
        assert response.json()["status"] == "started"

        release.set()
        assert failed.wait(2)
        body = _wait_for_status(client, "XAAPL-USDT", "1d", "backoff")
        assert body["status"] == "backoff"
    finally:
        release.set()
        scheduler.shutdown()


def test_invalid_bar_and_days_are_rejected_before_task(client: TestClient) -> None:
    seed_instruments(make_ref())
    calls: list[tuple[str, str, int]] = []

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar, days))

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    client.app.state.on_demand_sync = scheduler
    try:
        for payload in ({"bar": "5m"}, {"bar": "1d", "days": 0}, {"bar": "1d", "days": 3651}):
            response = client.post("/api/instruments/XAAPL-USDT/sync", json=payload)
            assert response.status_code == 422, response.text
        assert calls == []
    finally:
        scheduler.shutdown()


def test_unknown_instrument_is_404_before_task(client: TestClient) -> None:
    calls: list[tuple[str, str, int]] = []

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar, days))

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    client.app.state.on_demand_sync = scheduler
    try:
        response = client.post("/api/instruments/NOPE-USDT/sync", json={"bar": "1d"})
        assert response.status_code == 404
        assert calls == []
    finally:
        scheduler.shutdown()
