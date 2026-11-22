"""宏观端点：总览只读、并发刷新的单元锁、延迟标注与健康组件。"""

from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.core import UpstreamError
from app.macro import service as service_module
from app.market import exchange_session, settlement_epoch
from tests.macro.conftest import observation, provider_builder, seed

DAY = date(2026, 11, 20)
TS = settlement_epoch(DAY)


def _seed_full_curve() -> None:
    seed("us10y", ts=TS, value="4.92", provider="treasury", trading_day=DAY)
    seed("us2y", ts=TS, value="4.63", provider="treasury", trading_day=DAY)
    seed("us10y", ts=TS + 3600, value="4.90", provider="yahoo", trading_day=DAY, is_delayed=True)
    seed("vix", ts=TS + 3600, value="35.89", provider="yahoo", trading_day=DAY, is_delayed=True)
    seed("vix", ts=TS, value="35.89", provider="cboe", trading_day=DAY)


class _BlockingProvider:
    """在 `fetch` 里阻塞，用来制造「十个请求同时打同一个单元」的窗口。"""

    def __init__(self, name: str, release: threading.Event, counter: dict[str, int]) -> None:
        self.name = name
        self._release = release
        self._counter = counter
        self._lock = threading.Lock()

    def supports(self, series: object) -> bool:
        return True

    def fetch(self, series, since):
        with self._lock:
            self._counter["calls"] += 1
            order = self._counter["calls"]
        if order <= 5:
            self._release.wait(timeout=5)
        return [
            observation(series_id, ts=TS + order, value="1", provider=self.name)
            for series_id in series
        ]


def test_overview_returns_readings_with_delay_flags(client: TestClient) -> None:
    _seed_full_curve()

    body = client.get("/api/macro/overview").json()

    by_key = {(item["series_id"], item["granularity"]): item for item in body["readings"]}
    assert set(by_key) == {
        ("us10y", "minute"),
        ("us10y", "daily"),
        ("us2y", "daily"),
        ("vix", "minute"),
        ("vix", "daily"),
    }
    minute_ten = by_key[("us10y", "minute")]
    assert minute_ten["value"] == "4.9"
    assert minute_ten["is_delayed"] is True
    assert minute_ten["regime"] is None
    assert minute_ten["market_session"] == exchange_session(
        datetime.fromtimestamp(TS + 3600, tz=UTC)
    )

    daily_ten = by_key[("us10y", "daily")]
    assert daily_ten["is_delayed"] is False
    assert daily_ten["market_session"] == exchange_session(datetime.fromtimestamp(TS, tz=UTC))

    vix = by_key[("vix", "minute")]
    assert vix["regime"] == "panic"
    assert vix["value"] == "35.89"

    spread = body["spread"]
    assert spread["available"] is True
    assert spread["value_bp"] == "29"
    assert spread["inverted"] is False
    assert spread["trading_day"] == DAY.isoformat()
    assert spread["quality_status"] == "normal"
    assert spread["reason"] is None
    # AC3：利差行也要能追到来源。
    assert [source["provider"] for source in spread["sources"]] == ["treasury"]
    assert spread["sources"][0]["source_url"] is not None
    assert "treasury.gov" in spread["sources"][0]["source_url"]


def test_overview_is_200_and_stale_when_upstream_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_full_curve()
    before = client.get("/api/macro/overview").json()

    class Failing:
        name = "yahoo"

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series: object, since: object) -> list[object]:
            raise UpstreamError("宏观数据上游请求失败: 断网")

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: Failing())
    client.post("/api/macro/sync")

    response = client.get("/api/macro/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert "断网" in body["stale_reason"]
    # 数值一字不变：降级只是打标记，不填充假数据。
    assert [item["value"] for item in body["readings"]] == [
        item["value"] for item in before["readings"]
    ]


def test_overview_never_calls_provider(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_full_curve()
    calls = {"count": 0}

    def counting(name: str, **_: object) -> object:
        calls["count"] += 1
        raise AssertionError("总览不得请求上游")

    monkeypatch.setattr(service_module, "build_provider", counting)
    for _ in range(5):
        assert client.get("/api/macro/overview").status_code == 200

    assert calls["count"] == 0


def test_concurrent_sync_calls_upstream_once_per_unit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """10 个并发 POST：只让一批打上游（5 个单元各一次），其余 45 次整批跳过（AC6）。"""

    release = threading.Event()
    counter = {"calls": 0}
    monkeypatch.setattr(
        service_module,
        "build_provider",
        lambda name, **_: _BlockingProvider(name, release, counter),
    )

    def call(_: int):
        return client.post("/api/macro/sync")

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(call, index) for index in range(10)]
        # 第一批卡在第一个单元的上游请求里；其余 9 个请求应当立刻整批返回跳过。
        deadline = time.monotonic() + 10
        while counter["calls"] < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert counter["calls"] == 1
        while sum(future.done() for future in futures) < 9 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sum(future.done() for future in futures) == 9
        release.set()
        responses = [future.result(timeout=30) for future in futures]

    assert counter["calls"] == 5
    statuses = Counter(
        item["status"] for response in responses for item in response.json()["results"]
    )
    assert statuses == {"synced": 5, "skipped": 45}


def test_health_reports_macro_component(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        "us10y": [
            observation("us10y", ts=TS, value="4.92", provider="treasury"),
            observation("us10y", ts=TS + 60, value="4.91", provider="yahoo"),
        ],
        "us2y": [observation("us2y", ts=TS, value="4.63", provider="treasury")],
        "vix": [
            observation("vix", ts=TS, value="35.89", provider="cboe"),
            observation("vix", ts=TS + 60, value="35.90", provider="yahoo"),
        ],
    }
    monkeypatch.setattr(service_module, "build_provider", provider_builder(values))

    scheduler = client.app.state.market_data_scheduler
    scheduler.run_once()

    body = client.get("/api/system/health").json()
    macro = {item["name"]: item for item in body["components"]}["macro"]

    assert macro["status"] == "ok"
    assert macro["last_success_at"] is not None
    assert macro["error"] is None
    assert "上次运行" in macro["detail"]
    assert "下次" in macro["detail"]
    assert "耗时" in macro["detail"]


def test_sync_endpoint_reports_each_unit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {"vix": [observation("vix", ts=TS, value="35.89", provider="cboe")]}
    monkeypatch.setattr(service_module, "build_provider", provider_builder(values))

    body = client.post("/api/macro/sync").json()

    assert [item["series_id"] for item in body["results"]] == [
        "us10y",
        "us10y",
        "us2y",
        "vix",
        "vix",
    ]
    assert {item["status"] for item in body["results"]} <= {"synced", "failed", "skipped"}
    vix = next(item for item in body["results"] if item["series_id"] == "vix")
    assert vix["rows"] >= 0


def test_health_detail_counts_failures(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """一个单元失败时 detail 要写出「N 个失败」，不能只写「0 个降级」自相矛盾。"""

    class Failing:
        name = "fake"

        def supports(self, series: object) -> bool:
            return True

        def fetch(self, series: object, since: object) -> list[object]:
            from app.core import UpstreamError

            raise UpstreamError("上游 503")

    monkeypatch.setattr(service_module, "build_provider", lambda name, **_: Failing())
    scheduler = client.app.state.market_data_scheduler
    scheduler.run_once()

    body = client.get("/api/system/health").json()
    macro = {item["name"]: item for item in body["components"]}["macro"]

    assert macro["status"] == "error"
    assert "5 个失败" in macro["detail"]
