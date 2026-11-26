"""止损与订单历史的 HTTP 契约。

这一组覆盖 AC3 的四种情况与 AC6 的三个筛选：

| 情况 | 期望 |
| --- | --- |
| 有 algo 止损 | `confirmed` + 价位 |
| 订单带 `slTriggerPx` | `confirmed` + 价位 |
| 两者都无 | `none` |
| 接口失败 | `unavailable`（不是 `none`） |
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from app.main import create_app
from tests.exchange.conftest import SWAP_INST_ID, SWAP_INSTRUMENT
from tests.fakes.okx.server import FakeOkxServer

#: 订单 `cTime` 必须落在 `order_history` 的回溯窗口（最多 3 个月）里，否则会被
#: 「更早的订单不再返回」这条正确过滤剔除，用例就测不到内容。
_NOW_MS = int(time.time() * 1000)


def _minutes_ago(minutes: int) -> int:
    return _NOW_MS - minutes * 60_000


_ALGO_PATH = "/api/v5/trade/orders-algo-pending"
_PENDING_PATH = "/api/v5/trade/orders-pending"


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
        _seed_position(fake_okx_server)
        yield client
    get_settings.cache_clear()


def _seed_position(server: FakeOkxServer) -> None:
    book = server.store.book
    book.set_account(equity="1248.60", available_equity="682.30", used_margin="0")
    book.set_balance("USDT", available="682.30")
    book.set_position(
        SWAP_INST_ID,
        qty="8",
        pos_side="long",
        avg_price="226.80",
        pos_id="123456",
        mark_px="231.42",
        upl="36.96",
        lever="3",
        mgn_mode="isolated",
    )


def _cards(api: TestClient) -> dict:
    response = api.get("/api/positions/cards")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    return items[0]


def test_algo_stop_shows_up_on_the_card(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    fake_okx_server.store.book.set_stop(SWAP_INST_ID, stop_px="220", pos_side="long")

    assert api.post("/api/account/sync").status_code == 200

    card = _cards(api)
    assert card["stop_status"] == "confirmed"
    assert card["stop_px"] == "220"
    assert card["stop_distance_pct"] is not None


def test_no_stop_anywhere_is_reported_as_none(api: TestClient) -> None:
    assert api.post("/api/account/sync").status_code == 200

    assert _cards(api)["stop_status"] == "none"


def test_stop_endpoint_failure_is_reported_as_unavailable(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """止损查询失败不能拖垮整次同步，也不能降级成「未挂止损」。"""

    fake_okx_server.store.fail_paths.add(_ALGO_PATH)

    synced = api.post("/api/account/sync")

    assert synced.status_code == 200, synced.text
    card = _cards(api)
    assert card["stop_status"] == "unavailable"
    assert card["stop_px"] is None


def test_order_history_is_newest_first(api: TestClient, fake_okx_server: FakeOkxServer) -> None:
    book = fake_okx_server.store.book
    book.add_historical_order(
        SWAP_INST_ID, side="buy", qty="2", avg_px="100", created_at=_minutes_ago(30)
    )
    book.add_historical_order(
        SWAP_INST_ID, side="sell", qty="1", avg_px="110", pnl="2.5", created_at=_minutes_ago(10)
    )

    response = api.get(f"/api/positions/{SWAP_INST_ID}/orders")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inst_id"] == SWAP_INST_ID
    assert body["scope"] == "all"
    assert [item["side"] for item in body["items"]] == ["sell", "buy"]
    assert body["items"][0]["pnl"] == "2.5"


def test_order_history_scopes_filter_correctly(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    book = fake_okx_server.store.book
    book.add_historical_order(SWAP_INST_ID, side="buy", qty="2", created_at=_minutes_ago(30))
    book.add_historical_order(SWAP_INST_ID, state="live", qty="3", created_at=_minutes_ago(20))

    open_only = api.get(f"/api/positions/{SWAP_INST_ID}/orders?scope=open").json()
    history_only = api.get(f"/api/positions/{SWAP_INST_ID}/orders?scope=history").json()
    everything = api.get(f"/api/positions/{SWAP_INST_ID}/orders?scope=all").json()

    assert [item["is_open"] for item in open_only["items"]] == [True]
    assert [item["is_open"] for item in history_only["items"]] == [False]
    assert len(everything["items"]) == 2


def test_empty_order_history_is_an_empty_list_not_an_error(api: TestClient) -> None:
    response = api.get(f"/api/positions/{SWAP_INST_ID}/orders")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_order_history_upstream_failure_is_502(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    fake_okx_server.store.fail_paths.add(_PENDING_PATH)

    response = api.get(f"/api/positions/{SWAP_INST_ID}/orders")

    assert response.status_code == 502, response.text


def test_equity_curve_endpoint_returns_points(
    api: TestClient,
) -> None:
    assert api.post("/api/account/sync").status_code == 200

    response = api.get("/api/account/equity-curve?range=1d")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == "1d"
    # 刚写完一条快照：单点画不出线，因此不可用且没有点。
    assert body["available"] is False
    assert body["points"] == []
    assert body["first_snapshot_at"] is not None


def test_equity_curve_rejects_an_unknown_range(api: TestClient) -> None:
    assert api.get("/api/account/equity-curve?range=2d").status_code == 422


def test_failed_stop_fetch_does_not_raise_a_missing_stop_alert(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """「没查到止损」不能变成「未挂止损 3」——页面上下不能互相矛盾。

    构造方式与功能检测一致：只让止损两个端点失败，账户与持仓照常同步。此时 15 / 3
    张卡都显示「未取到」，/risk/exposure 里的 `stop_missing` 必须是 0 条。
    """

    fake_okx_server.store.fail_paths.update({_ALGO_PATH, _PENDING_PATH})

    assert api.post("/api/account/sync").status_code == 200
    card = _cards(api)
    assert card["stop_status"] == "unavailable"

    exposure = api.get("/api/risk/exposure")
    assert exposure.status_code == 200, exposure.text
    body = exposure.json()
    # 单标的占比 100% 会命中集中度规则，那是另一件事；这里只关心止损。
    assert "stop_missing" not in [rule["rule_id"] for rule in body["rules"]]
    position = body["positions"][0]
    assert position["stop_status"] == "unavailable"
    assert "stop_missing" not in position["flags"]


def test_confirmed_absence_of_a_stop_still_raises_the_rule(
    api: TestClient,
) -> None:
    assert api.post("/api/account/sync").status_code == 200

    assert _cards(api)["stop_status"] == "none"

    body = api.get("/api/risk/exposure").json()
    assert "stop_missing" in [rule["rule_id"] for rule in body["rules"]]
    assert body["positions"][0]["stop_status"] == "none"


def test_exchange_stop_reaches_the_risk_layer(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """OKX 上挂了止损，风险层必须看到它，而不是只认本地配置。"""

    fake_okx_server.store.book.set_stop(SWAP_INST_ID, stop_px="220", pos_side="long")
    assert api.post("/api/account/sync").status_code == 200

    body = api.get("/api/risk/exposure").json()

    assert "stop_missing" not in [rule["rule_id"] for rule in body["rules"]]
    position = body["positions"][0]
    assert position["stop_status"] == "confirmed"
    assert position["stop_px"] == "220"
