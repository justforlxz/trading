"""标的端点：搜索、详情（含对手腿报价）、K 线窗口的契约与错误路径。"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.api.conftest import seed_daily, seed_instruments
from tests.factories.instruments import make_ref, make_swap_ref

DECIMAL = re.compile(r"^-?\d{1,20}(\.\d{1,12})?$")
UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_search_matches_symbol_and_product_key(market_data: TestClient) -> None:
    """搜索对 symbol 与 product_key 都做大小写不敏感匹配。"""

    response = market_data.get("/api/instruments/search", params={"q": "aapl"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["inst_id"] for item in items] == ["AAPL-USDT-SWAP", "XAAPL-USDT"]
    assert items[1]["inst_type"] == "SPOT"
    assert items[1]["product_key"] == "AAPL"


def test_search_filters_by_inst_type(market_data: TestClient) -> None:
    """inst_type 可以把结果收窄到单一形态。"""

    response = market_data.get("/api/instruments/search", params={"q": "aapl", "inst_type": "SWAP"})

    assert response.status_code == 200
    assert [item["inst_id"] for item in response.json()["items"]] == ["AAPL-USDT-SWAP"]


def test_search_without_hits_is_empty_not_404(market_data: TestClient) -> None:
    """没有命中就是空列表。"""

    response = market_data.get("/api/instruments/search", params={"q": "zzz"})

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_search_requires_query(market_data: TestClient) -> None:
    """缺 q 由查询参数校验拒绝。"""

    response = market_data.get("/api/instruments/search")

    assert response.status_code == 422
    assert response.json()["detail"]


def test_search_rejects_blank_query(market_data: TestClient) -> None:
    """纯空格没有检索意义，同样按 422 拒绝。"""

    response = market_data.get("/api/instruments/search", params={"q": "   "})

    assert response.status_code == 422
    assert response.json()["detail"]


def test_detail_picks_the_other_form_not_the_other_quote(client: TestClient) -> None:
    """同一产品两条现货加一条永续：任一现货的对手腿都是永续，不是另一条现货。"""

    seed_instruments(
        make_ref(),
        make_ref(inst_id="XAAPL-USDC", base_ccy="XAAPL", quote_ccy="USDC"),
        make_swap_ref(),
    )
    seed_daily("XAAPL-USDT", ["100", "110", "121"])
    seed_daily("XAAPL-USDC", ["100", "110", "120"])
    seed_daily("AAPL-USDT-SWAP", ["50", "55", "60.5"])

    usdc_spot = client.get("/api/instruments/XAAPL-USDC").json()
    assert [sibling["inst_id"] for sibling in usdc_spot["siblings"]] == ["AAPL-USDT-SWAP"]
    assert usdc_spot["siblings"][0]["inst_type"] == "SWAP"

    usdt_spot = client.get("/api/instruments/XAAPL-USDT").json()
    assert [sibling["inst_id"] for sibling in usdt_spot["siblings"]] == ["AAPL-USDT-SWAP"]

    swap = client.get("/api/instruments/AAPL-USDT-SWAP").json()
    assert [sibling["inst_id"] for sibling in swap["siblings"]] == ["XAAPL-USDT"]


def test_detail_from_the_swap_side_reports_the_spot_leg(market_data: TestClient) -> None:
    """从永续一侧看详情，对手腿必须是现货——反过来写死的实现过不了这一条。"""

    response = market_data.get("/api/instruments/AAPL-USDT-SWAP")

    assert response.status_code == 200
    body = response.json()
    assert body["instrument"]["inst_type"] == "SWAP"
    assert body["siblings"] == [
        {
            "inst_id": "XAAPL-USDT",
            "inst_type": "SPOT",
            "last_price": "121",
            # 60.5 / 121 - 1 = -50%
            "price_spread_pct": "-50",
        }
    ]


def test_detail_reports_metadata_and_sibling_quote(market_data: TestClient) -> None:
    """详情返回标的全字段，以及另一形态的最近收盘与价差。"""

    response = market_data.get("/api/instruments/XAAPL-USDT")

    assert response.status_code == 200
    body = response.json()
    instrument = body["instrument"]
    assert instrument["inst_id"] == "XAAPL-USDT"
    assert instrument["inst_type"] == "SPOT"
    assert instrument["product_key"] == "AAPL"
    assert instrument["asset_type"] == "tokenized_equity"
    assert instrument["trading_status"] == "live"
    assert DECIMAL.match(instrument["tick_size"]) is not None
    assert UTC_ZULU.match(instrument["listing_time"]) is not None
    assert body["latest_signal"] is None
    assert body["siblings"] == [
        {
            "inst_id": "AAPL-USDT-SWAP",
            "inst_type": "SWAP",
            "last_price": "60.5",
            # 121 / 60.5 - 1 = 100%
            "price_spread_pct": "100",
        }
    ]


def test_detail_without_quotes_leaves_siblings_empty(quote_less_instrument: TestClient) -> None:
    """对手腿没有日线时不编造价差，直接给空列表。"""

    seed_instruments(make_ref())

    response = quote_less_instrument.get("/api/instruments/XAAPL-USDT")

    assert response.status_code == 200
    assert response.json()["siblings"] == []


def test_detail_unknown_instrument_is_404(market_data: TestClient) -> None:
    """未同步的标的没有详情。"""

    response = market_data.get("/api/instruments/NOPE-USDT")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_candles_window_reports_available_range(market_data: TestClient) -> None:
    """K 线窗口取最后 limit 根，同时给出库里真实的可用区间。"""

    response = market_data.get(
        "/api/instruments/XAAPL-USDT/candles", params={"bar": "1d", "limit": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["inst_id"] == "XAAPL-USDT"
    assert body["bar"] == "1d"
    assert body["data_source"] == "okx"
    assert body["has_gap"] is False
    assert [candle["close"] for candle in body["candles"]] == ["110", "121"]
    assert [candle["is_closed"] for candle in body["candles"]] == [True, True]
    assert UTC_ZULU.match(body["available_from"]) is not None
    assert UTC_ZULU.match(body["available_to"]) is not None
    assert body["candles"][-1]["open_time"] == body["available_to"]
    assert DECIMAL.match(body["candles"][0]["volume"]) is not None


def test_candles_without_data_are_empty(market_data: TestClient) -> None:
    """没有 K 线时给空序列，并如实说明没有可用区间。"""

    seed_instruments(make_ref(inst_id="XETH-USDT", base_ccy="XETH"))

    response = market_data.get("/api/instruments/XETH-USDT/candles", params={"bar": "1d"})

    assert response.status_code == 200
    body = response.json()
    assert body["candles"] == []
    assert body["available_from"] is None
    assert body["available_to"] is None
    assert body["has_gap"] is False


def test_candles_reject_out_of_range_limit(market_data: TestClient) -> None:
    """limit 上限 1000。"""

    response = market_data.get(
        "/api/instruments/XAAPL-USDT/candles", params={"bar": "1d", "limit": 1001}
    )

    assert response.status_code == 422
    assert response.json()["detail"]


def test_candles_unknown_instrument_is_404(market_data: TestClient) -> None:
    """未同步的标的没有 K 线。"""

    response = market_data.get("/api/instruments/NOPE-USDT/candles", params={"bar": "1d"})

    assert response.status_code == 404
    assert response.json()["detail"]


def test_non_equity_asset_types_and_upstream_states_are_readable(client: TestClient) -> None:
    """商品代币、未登记分类与停牌状态都能读出：契约覆盖领域层的真实取值。"""

    seed_instruments(
        make_ref(inst_id="XAUT-USDT", base_ccy="XAUT", inst_category="4"),
        make_ref(inst_id="XSPCX-USDT", base_ccy="XSPCX", inst_category="9"),
        make_ref(inst_id="XTSLA-USDT", base_ccy="XTSLA", state="suspend"),
    )

    search = client.get("/api/instruments/search", params={"q": "x"})

    assert search.status_code == 200
    by_id = {item["inst_id"]: item for item in search.json()["items"]}
    assert by_id["XAUT-USDT"]["asset_type"] == "commodity_token"
    assert by_id["XSPCX-USDT"]["asset_type"] == "unknown"

    detail = client.get("/api/instruments/XTSLA-USDT")

    assert detail.status_code == 200
    assert detail.json()["instrument"]["trading_status"] == "suspend"
