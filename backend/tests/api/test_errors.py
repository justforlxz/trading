"""上游故障的对外文案：用户看到的必须是能据此行动的一句话。

上游异常消息里带着接口路径、查询串、返回码与底层网络错误（`[Errno 104] Connection
reset by peer`）。把它原样塞进响应体，用户既看不懂，也无法判断「是没订单、还是查不到」。
这里守住三条：

1. 响应体只有固定可读文案，不含路径 / errno / 异常原文；
2. HTTP 状态仍是 502（上游故障，不是参数错误）；
3. 原始信息不丢——服务端日志里带着完整异常。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.errors import _public_detail
from app.config import get_settings
from app.core import (
    Conflict,
    DataUnavailable,
    ExecutionRejected,
    NotFound,
    UnprocessableEntity,
    UpstreamError,
    ValidationError,
)
from app.exchange import ExchangeError, RateLimitedError
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from app.main import create_app
from tests.exchange.conftest import SWAP_INST_ID, SWAP_INSTRUMENT
from tests.fakes.okx.server import FakeOkxServer

#: 响应体里绝不允许出现的片段：内部实现细节。
LEAKS = ("/api/v5/", "Errno", "Connection reset", "Traceback", "httpx")


@pytest.fixture()
def api(fake_okx_server: FakeOkxServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    credentials = fake_okx_server.store.book.credentials
    monkeypatch.setenv("OKX_API_KEY", credentials.api_key)
    monkeypatch.setenv("OKX_SECRET_KEY", credentials.secret)
    monkeypatch.setenv("OKX_PASSPHRASE", credentials.passphrase)
    monkeypatch.setenv("OKX_DEMO", "1")
    monkeypatch.setenv("OKX_REST_BASE_URL", fake_okx_server.base_url)
    monkeypatch.setenv("OKX_HTTP_MAX_RETRIES", "0")
    monkeypatch.setenv("OKX_RATE_LIMIT_CAPACITY", "1000")
    monkeypatch.setenv("OKX_RATE_LIMIT_REFILL_PER_SECOND", "1000")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
        yield client
    get_settings.cache_clear()


def _assert_clean(detail: str) -> None:
    for fragment in LEAKS:
        assert fragment not in detail, f"响应体泄露了 {fragment!r}：{detail}"


# ------------------------------------------------------------------ 文案映射


def test_upstream_error_maps_to_a_readable_message() -> None:
    detail = _public_detail(ExchangeError("请求 /api/v5/trade/orders 失败:[Errno 104] x"))

    _assert_clean(detail)
    assert detail == "上游数据源暂时不可用，请稍后重试"


def test_rate_limited_has_its_own_message() -> None:
    detail = _public_detail(RateLimitedError("请求 /api/v5/trade/orders 返回 HTTP 429"))

    _assert_clean(detail)
    assert detail == "请求太频繁，请稍后重试"


def test_domain_errors_keep_their_own_message() -> None:
    """领域错误本来就该让用户看到——那是他能据此行动的信息。"""

    assert _public_detail(ValidationError("数量必须大于 0")) == "数量必须大于 0"
    assert _public_detail(NotFound("未找到持仓 manual:1")) == "未找到持仓 manual:1"
    assert _public_detail(Conflict("已停用")) == "已停用"
    assert _public_detail(UnprocessableEntity("减仓数量超过持仓")) == "减仓数量超过持仓"
    assert _public_detail(ExecutionRejected("余额不足")) == "余额不足"
    assert _public_detail(DataUnavailable("标的未同步")) == "标的未同步"
    assert _public_detail(UpstreamError("任意上游故障")) == "上游数据源暂时不可用，请稍后重试"


# ------------------------------------------------------------------ 逐端点


def test_account_sync_failure_is_clean_and_logged(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")

    with caplog.at_level(logging.WARNING, logger="app.api.errors"):
        response = api.post("/api/account/sync")

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    _assert_clean(detail)
    # 原始信息没丢：日志里有方法、路径与上游返回码
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "/api/account/sync" in logged
    assert "50011" in logged or "ExchangeError" in logged or "429" in logged or "500" in logged


def test_order_history_failure_is_clean_and_logged(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_okx_server.store.fail_paths.add("/api/v5/trade/orders-pending")

    with caplog.at_level(logging.WARNING, logger="app.api.errors"):
        response = api.get(f"/api/positions/{SWAP_INST_ID}/orders")

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    _assert_clean(detail)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    # 日志里必须能定位到是哪一次上游请求
    assert "/api/positions/" in logged


def test_stop_read_failure_degrades_instead_of_failing_the_sync(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """止损读取失败不返回 502：同步照常完成，止损三态标「未取到」。

    这是「同一个 ExchangeError 两种处置」的对照——账户与持仓读不到就是整体失败，
    止损读不到只影响止损这一项，不能把整页打掉。
    """

    book = fake_okx_server.store.book
    book.set_account(equity="1000", available_equity="800")
    book.set_position(
        SWAP_INST_ID,
        qty="1",
        pos_side="long",
        avg_price="100",
        pos_id="pos-1",
        mark_px="101",
        lever="3",
    )
    fake_okx_server.store.fail_paths.add("/api/v5/trade/orders-algo-pending")

    with caplog.at_level(logging.WARNING, logger="app.api.errors"):
        response = api.post("/api/account/sync")

    assert response.status_code == 200, response.text
    cards = api.get("/api/positions/cards").json()["items"]
    assert [card["stop_status"] for card in cards] == ["unavailable"]
    # 止损读取失败由 positions 域自己记活动事件，不经过 API 边界
    assert not [
        record for record in caplog.records if "上游数据源暂时不可用" in record.getMessage()
    ]
