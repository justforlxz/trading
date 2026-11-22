"""系统健康：真实检查、失败降级与已删除的外部 Provider 组件不再出现。

`macro` 与 `equity` 两组件的状态由装配层从调度器读来；没有调度器时如实报未配置，
本文件只断言组件的存在与降级口径。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.market import finish_sync_job, start_sync_job, system_health
from app.market.health import ComponentHealth


class _FixedClock:
    """固定时刻的时钟：让任务流水落在指定时间，用来构造「很久没同步」。"""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def _components(body: dict) -> dict[str, dict]:
    return {item["name"]: item for item in body["components"]}


def test_health_reports_every_component(client: TestClient) -> None:
    body = client.get("/api/system/health").json()

    assert set(body) == {"status", "checked_at", "components"}
    names = [item["name"] for item in body["components"]]
    assert names == [
        "database",
        "okx_rest",
        "okx_ws",
        "job_queue",
        "candle_coverage",
        "macro",
        "equity",
    ]
    assert "external_provider" not in names
    database = _components(body)["database"]
    assert database["status"] == "ok"
    assert database["last_success_at"] is not None
    ws = _components(body)["okx_ws"]
    assert ws["status"] == "unconfigured"
    assert body["status"] == "degraded"


def test_health_marks_okx_rest_stale_after_failed_sync(client: TestClient) -> None:
    job = start_sync_job("okx", "candles")
    finish_sync_job(job.id, "failed", error="连接被拒绝")

    body = client.get("/api/system/health").json()

    okx = _components(body)["okx_rest"]
    assert okx["status"] == "stale"
    assert "连接被拒绝" in okx["error"]


def test_health_marks_okx_rest_stale_while_sync_is_running(client: TestClient) -> None:
    start_sync_job("okx", "candles")

    body = client.get("/api/system/health").json()

    okx = _components(body)["okx_rest"]
    assert okx["status"] == "stale"
    assert "仍在运行" in okx["detail"]


def test_health_marks_okx_rest_stale_when_success_is_old(client: TestClient) -> None:
    old = datetime.now(UTC) - timedelta(days=30)
    job = start_sync_job("okx", "candles", clock=_FixedClock(old))
    finish_sync_job(job.id, "succeeded", rows=10, clock=_FixedClock(old))

    body = client.get("/api/system/health").json()

    okx = _components(body)["okx_rest"]
    assert okx["status"] == "stale"
    assert "超过 3 天" in okx["detail"]


def test_health_job_queue_recovers_after_a_newer_success(client: TestClient) -> None:
    """失败之后又成功：队列必须回到 ok，不能一直停在 stale。"""

    failed_at = datetime.now(UTC) - timedelta(hours=2)
    failed = start_sync_job("okx", "candles", clock=_FixedClock(failed_at))
    finish_sync_job(failed.id, "failed", error="上游不可用", clock=_FixedClock(failed_at))
    retried_at = datetime.now(UTC) - timedelta(minutes=5)
    retried = start_sync_job("okx", "candles", clock=_FixedClock(retried_at))
    finish_sync_job(retried.id, "succeeded", rows=3, clock=_FixedClock(retried_at))

    body = client.get("/api/system/health").json()

    queue = _components(body)["job_queue"]
    assert queue["status"] == "ok"
    assert queue["error"] is None
    assert "最近失败 0" in queue["detail"]


def test_health_job_queue_stays_stale_when_failure_is_newer(client: TestClient) -> None:
    """失败发生在最近一次成功之后，才是尚未恢复的失败。"""

    ok_at = datetime.now(UTC) - timedelta(hours=2)
    succeeded = start_sync_job("okx", "candles", clock=_FixedClock(ok_at))
    finish_sync_job(succeeded.id, "succeeded", rows=3, clock=_FixedClock(ok_at))
    failed_at = datetime.now(UTC) - timedelta(hours=1)
    failed = start_sync_job("okx", "candles", clock=_FixedClock(failed_at))
    finish_sync_job(failed.id, "failed", error="上游不可用", clock=_FixedClock(failed_at))

    body = client.get("/api/system/health").json()

    queue = _components(body)["job_queue"]
    assert queue["status"] == "stale"
    assert "上游不可用" in queue["error"]


def test_health_detail_reports_subscription_counts_and_skipped(client: TestClient) -> None:
    """AC5：超限跳过的订阅写在 `okx_ws` 的 detail 里，不静默丢弃。"""

    health = system_health(
        ws_status={
            "provider": "okx",
            "dataset": "public_ws",
            "connected": True,
            "subscriptions": 40,
            "skipped": 2,
            "candle": {"connected": True, "subscriptions": 40, "skipped": 0},
        }
    )

    ws = {item.name: item for item in health.components}["okx_ws"]
    assert ws.status == "ok"
    assert ws.detail == "okx / public_ws；订阅 40 个标的，跳过 2 个（超限）；K 线订阅 40 个标的"


def _equity_component(status: dict | None) -> ComponentHealth:
    health = system_health(
        macro_status=None,
        equity_status=status,
        clock=_FixedClock(datetime(2026, 11, 22, 7, 30, tzinfo=UTC)),
    )
    return {item.name: item for item in health.components}["equity"]


def test_equity_component_reports_ok_inside_the_freshness_window() -> None:
    component = _equity_component(
        {
            "last_success_at": "2026-11-22T07:25:00Z",
            "last_run_at": "2026-11-22T07:25:00Z",
            "next_run_at": "2026-11-22T07:26:00Z",
            "duration_ms": 812,
            "last_error": None,
            "failures": 0,
            "degraded": False,
        }
    )

    assert component.status == "ok"
    assert "耗时 812ms" in (component.detail or "")
    assert component.last_success_at == datetime(2026, 11, 22, 7, 25, tzinfo=UTC)


def test_equity_component_reports_stale_after_an_hour() -> None:
    component = _equity_component(
        {
            "last_success_at": "2026-11-22T05:00:00Z",
            "last_error": None,
            "degraded": False,
        }
    )

    assert component.status == "stale"
    assert "1 小时" in (component.detail or "")


def test_equity_component_reports_error_with_the_upstream_message() -> None:
    component = _equity_component(
        {
            "last_success_at": "2026-11-22T07:25:00Z",
            "last_error": "Yahoo 行情上游返回 HTTP 429",
            "degraded": True,
            "failures": 3,
        }
    )

    assert component.status == "error"
    assert component.error == "Yahoo 行情上游返回 HTTP 429"
    assert "连续失败 3 次" in (component.detail or "")


def test_equity_component_is_unconfigured_without_a_scheduler() -> None:
    component = _equity_component(None)

    assert component.status == "unconfigured"
    assert component.last_success_at is None
