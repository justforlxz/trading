"""系统健康与手动同步：真实检查、失败降级、任务流水与冲突。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.market import (
    EventInput,
    NewsInput,
    ProviderQuote,
    finish_sync_job,
    register_provider,
    start_sync_job,
)


class StaticProvider:
    name = "fake"

    def overview(self) -> Sequence[ProviderQuote]:
        return (
            ProviderQuote(
                symbol="NASDAQ",
                value=Decimal("18000"),
                as_of=datetime(2026, 11, 15, 6, 0, tzinfo=UTC),
            ),
        )

    def events(self, *, start: datetime, end: datetime) -> Sequence[EventInput]:
        return ()

    def news(self, *, tickers: Sequence[str], limit: int) -> Sequence[NewsInput]:
        return ()


class _FixedClock:
    """固定时刻的时钟：让任务流水落在指定时间，用来构造「很久没同步」。"""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.fixture(autouse=True)
def provider() -> None:
    register_provider("fake", StaticProvider, replace=True)


def _use_provider(client: TestClient) -> None:
    response = client.patch("/api/settings", json={"data_sources": {"provider": "fake"}})
    assert response.status_code == 200, response.text


def test_health_reports_every_component(client: TestClient) -> None:
    body = client.get("/api/system/health").json()

    assert set(body) == {"status", "checked_at", "components"}
    names = [item["name"] for item in body["components"]]
    assert names == [
        "database",
        "okx_rest",
        "okx_ws",
        "external_provider",
        "job_queue",
        "candle_coverage",
    ]
    database = next(item for item in body["components"] if item["name"] == "database")
    assert database["status"] == "ok"
    assert database["last_success_at"] is not None
    ws = next(item for item in body["components"] if item["name"] == "okx_ws")
    assert ws["status"] == "unconfigured"
    assert body["status"] == "degraded"


def test_health_marks_okx_rest_stale_after_failed_sync(client: TestClient) -> None:
    job = start_sync_job("okx", "candles")
    finish_sync_job(job.id, "failed", error="连接被拒绝")

    body = client.get("/api/system/health").json()

    okx = next(item for item in body["components"] if item["name"] == "okx_rest")
    assert okx["status"] == "stale"
    assert "连接被拒绝" in okx["error"]


def test_health_marks_external_provider_stale(client: TestClient) -> None:
    _use_provider(client)
    job = start_sync_job("fake", "market_overview")
    finish_sync_job(job.id, "failed", error="Provider 超时")

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "stale"
    assert "超时" in provider["error"]
    assert "fake / market_overview" in provider["detail"]


def test_health_reports_provider_ok_after_success(client: TestClient) -> None:
    _use_provider(client)
    job = start_sync_job("fake", "market_overview")
    finish_sync_job(job.id, "succeeded", rows=4)

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "ok"
    assert provider["last_success_at"] is not None
    assert "仍在时效内" in provider["detail"]


def test_health_marks_provider_stale_when_last_success_is_old(client: TestClient) -> None:
    """成功过一次但早已超过时效时报告 stale，detail 不能写“同步成功”。"""

    _use_provider(client)
    old = datetime.now(UTC) - timedelta(days=3)
    job = start_sync_job("fake", "market_overview", clock=_FixedClock(old))
    finish_sync_job(job.id, "succeeded", rows=4, clock=_FixedClock(old))

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "stale"
    assert provider["last_success_at"] is not None
    assert "同步成功" not in provider["detail"]
    assert "超过 24 小时未更新" in provider["detail"]
    assert provider["error"] is None


def test_health_marks_provider_stale_while_sync_is_running(client: TestClient) -> None:
    """running 只说明任务没结束，不能报告为 ok，也不能写“同步成功”。"""

    _use_provider(client)
    start_sync_job("fake", "market_overview")

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "stale"
    assert "仍在运行" in provider["detail"]
    assert "同步成功" not in provider["detail"]


def test_health_keeps_provider_stale_when_other_dataset_synced(client: TestClient) -> None:
    """新鲜度按数据集计算：news 刚成功，不能把过期的 market_overview 洗成 ok。"""

    _use_provider(client)
    old = datetime.now(UTC) - timedelta(days=3)
    stale_job = start_sync_job("fake", "market_overview", clock=_FixedClock(old))
    finish_sync_job(stale_job.id, "succeeded", rows=4, clock=_FixedClock(old))
    fresh_job = start_sync_job("fake", "news")
    finish_sync_job(fresh_job.id, "succeeded", rows=7)

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "stale"
    assert provider["last_success_at"] is not None
    # 返回的必须是 market_overview 自己的最后成功时间，而不是新闻同步时间。
    reported = datetime.fromisoformat(provider["last_success_at"].replace("Z", "+00:00"))
    assert reported == old.replace(microsecond=0)
    assert "超过 24 小时未更新" in provider["detail"]


def test_health_marks_provider_stale_when_quote_time_is_old(client: TestClient) -> None:
    """同步任务刚结束但报价本身很旧时，不能报告为 ok。"""

    _use_provider(client)
    old = datetime.now(UTC) - timedelta(days=3)

    class OldQuoteProvider(StaticProvider):
        def overview(self) -> Sequence[ProviderQuote]:
            return (
                ProviderQuote(
                    symbol="NASDAQ",
                    value=Decimal("18000"),
                    as_of=old,
                ),
            )

    register_provider("fake", OldQuoteProvider, replace=True)
    synced = client.post("/api/system/sync", json={"dataset": "market_overview"})
    assert synced.status_code == 202, synced.text

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "stale"
    assert "报价" in provider["detail"]
    assert provider["error"] is None


def test_health_reports_provider_ok_when_quote_time_is_fresh(client: TestClient) -> None:
    """报价时间在新鲜度阈值内时仍然报告 ok。"""

    _use_provider(client)

    class FreshQuoteProvider(StaticProvider):
        def overview(self) -> Sequence[ProviderQuote]:
            return (
                ProviderQuote(
                    symbol="NASDAQ",
                    value=Decimal("18000"),
                    as_of=datetime.now(UTC),
                ),
            )

    register_provider("fake", FreshQuoteProvider, replace=True)
    synced = client.post("/api/system/sync", json={"dataset": "market_overview"})
    assert synced.status_code == 202, synced.text

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "ok"
    assert "仍在时效内" in provider["detail"]


def test_health_returns_job_queue_to_ok_after_retry_succeeds(client: TestClient) -> None:
    """历史失败记录不清理，恢复后队列必须回到 ok，不能一直停在 stale。"""

    failed_at = datetime.now(UTC) - timedelta(hours=2)
    failed = start_sync_job("fake", "news", clock=_FixedClock(failed_at))
    finish_sync_job(failed.id, "failed", error="Provider 超时", clock=_FixedClock(failed_at))
    retried_at = datetime.now(UTC) - timedelta(minutes=5)
    retried = start_sync_job("fake", "news", clock=_FixedClock(retried_at))
    finish_sync_job(retried.id, "succeeded", rows=3, clock=_FixedClock(retried_at))

    body = client.get("/api/system/health").json()

    queue = next(item for item in body["components"] if item["name"] == "job_queue")
    assert queue["status"] == "ok"
    assert queue["error"] is None
    assert "最近失败 0" in queue["detail"]


def test_health_keeps_job_queue_stale_when_failure_is_newer(client: TestClient) -> None:
    """失败发生在最近一次成功之后，才是尚未恢复的失败。"""

    ok_at = datetime.now(UTC) - timedelta(hours=2)
    succeeded = start_sync_job("fake", "news", clock=_FixedClock(ok_at))
    finish_sync_job(succeeded.id, "succeeded", rows=3, clock=_FixedClock(ok_at))
    failed_at = datetime.now(UTC) - timedelta(hours=1)
    failed = start_sync_job("fake", "news", clock=_FixedClock(failed_at))
    finish_sync_job(failed.id, "failed", error="Provider 超时", clock=_FixedClock(failed_at))

    body = client.get("/api/system/health").json()

    queue = next(item for item in body["components"] if item["name"] == "job_queue")
    assert queue["status"] == "stale"
    assert "Provider 超时" in queue["error"]


def test_health_reports_provider_settings_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """设置表读不出来时要说明是这个原因，不能报成「未配置 Provider」。"""

    from app.api.routes import system as system_routes

    def broken() -> str | None:
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(system_routes, "configured_provider_name", broken)

    body = client.get("/api/system/health").json()

    provider = next(item for item in body["components"] if item["name"] == "external_provider")
    assert provider["status"] == "error"
    assert "设置" in (provider["detail"] or "")


def test_health_marks_okx_rest_stale_while_sync_is_running(client: TestClient) -> None:
    start_sync_job("okx", "candles")

    body = client.get("/api/system/health").json()

    okx = next(item for item in body["components"] if item["name"] == "okx_rest")
    assert okx["status"] == "stale"
    assert "仍在运行" in okx["detail"]


def test_health_marks_okx_rest_stale_when_success_is_old(client: TestClient) -> None:
    old = datetime.now(UTC) - timedelta(days=30)
    job = start_sync_job("okx", "candles", clock=_FixedClock(old))
    finish_sync_job(job.id, "succeeded", rows=10, clock=_FixedClock(old))

    body = client.get("/api/system/health").json()

    okx = next(item for item in body["components"] if item["name"] == "okx_rest")
    assert okx["status"] == "stale"
    assert "超过 3 天" in okx["detail"]


def test_sync_runs_synchronously_and_writes_job(client: TestClient) -> None:
    _use_provider(client)

    response = client.post("/api/system/sync", json={"dataset": "market_overview"})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["job_id"].startswith("job_")
    assert body["rows"] == 1

    health = client.get("/api/system/health").json()
    provider = next(item for item in health["components"] if item["name"] == "external_provider")
    assert provider["status"] == "ok"


def test_sync_rejects_unknown_dataset(client: TestClient) -> None:
    _use_provider(client)

    response = client.post("/api/system/sync", json={"dataset": "unknown"})

    assert response.status_code == 400
    assert "未知数据集" in response.json()["detail"]


def test_sync_requires_provider(client: TestClient) -> None:
    response = client.post("/api/system/sync", json={"dataset": "market_overview"})

    assert response.status_code == 400
    assert "Provider" in response.json()["detail"]


def test_sync_conflicts_with_running_job(client: TestClient) -> None:
    _use_provider(client)
    start_sync_job("fake", "news")

    response = client.post("/api/system/sync", json={"dataset": "news"})

    assert response.status_code == 409
    assert "仍在运行" in response.json()["detail"]


def test_sync_failure_is_recorded_and_returned(client: TestClient) -> None:
    _use_provider(client)

    class BrokenProvider(StaticProvider):
        def overview(self):
            raise RuntimeError("上游不可用")

    register_provider("fake", BrokenProvider, replace=True)

    response = client.post("/api/system/sync", json={"dataset": "market_overview"})

    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "RuntimeError"
