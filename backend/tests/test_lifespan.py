"""lifespan 的测试模式开关：生产路径照常启动后台服务，测试模式只装请求处理路径。

生产路径必须能被重复验证，所以这里显式把 `TEST_MODE` 关掉再建应用：权益快照线程与
常驻推送集线器都要真的起来，退出时再被 lifespan 收拾干净。
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.stream import StreamHub
from tests.fakes.on_demand import RecordingScheduler

EQUITY_THREAD_NAME = "trading-equity-snapshot"


def _equity_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == EQUITY_THREAD_NAME]


def test_test_mode_skips_background_services(client: TestClient) -> None:
    """`TEST_MODE=1`：不建推送集线器，也不起权益快照线程。"""

    assert not hasattr(client.app.state, "stream_hub")
    assert _equity_threads() == []


def test_production_mode_starts_the_equity_scheduler_and_stream_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`TEST_MODE` 关闭时（生产路径）：两条后台服务都启动，退出后线程收干净。"""

    monkeypatch.setenv("TEST_MODE", "0")
    get_settings.cache_clear()
    try:
        with TestClient(create_app(on_demand_sync=RecordingScheduler())) as test_client:
            assert isinstance(test_client.app.state.stream_hub, StreamHub)
            assert len(_equity_threads()) == 1
    finally:
        get_settings.cache_clear()

    assert _equity_threads() == []
