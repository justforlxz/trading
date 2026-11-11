"""关系网络端点：真实落库数据 → TestClient 的整图与邻居。

行情用固定的 2026-11-01 起四根日线，三组收盘价按中心化向量手算 Pearson：

- AAPL = 10, 12, 14, 16（中心化 -3, -1, 1, 3）
- MSFT = 101, 103, 99, 97（中心化 1, 3, -1, -3）→ 与 AAPL 相关 -0.8
- NVDA = 30, 32, 34, 36（与 AAPL 同形）→ 与 AAPL 相关 +1.0，与 MSFT 相关 -0.8
- TSLA = 52, 48, 52, 48 → 与任何人的 |相关| 都低于 0.5，成为孤立节点

因为只有一条正边，社区是 {AAPL, NVDA} 与两个单点社区；三条边的度数之和为 6 = 2E，
平均连通度 2E/V = 1.5。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import Bar, InstrumentRef, Timeframe
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.watchlist import add_item

DECIMAL = re.compile(r"^-?\d{1,20}(\.\d{1,12})?$")
UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

START = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)
BAR = "1d"
WINDOW = 4
QUERY = {"bar": BAR, "window": WINDOW, "min_abs_corr": 0.5}

CLOSES = {
    "AAPL": ("XAAPL-USDT", ["10", "12", "14", "16"]),
    "MSFT": ("XMSFT-USDT", ["101", "103", "99", "97"]),
    "NVDA": ("XNVDA-USDT", ["30", "32", "34", "36"]),
    "TSLA": ("XTSLA-USDT", ["52", "48", "52", "48"]),
}


def _write_daily(inst_id: str, closes: list[str]) -> None:
    """把收盘序列写成一串已完结日线；时间固定在 `START` 起，不用「现在」。"""

    rows = [
        Bar(
            inst_id=inst_id,
            timeframe=Timeframe.parse(BAR),
            open_time=START + timedelta(days=index),
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("10"),
            confirm=True,
            source="okx_spot",
        )
        for index, close in enumerate(closes)
    ]
    upsert_candles(rows)


@pytest.fixture
def network(client: TestClient) -> TestClient:
    """四个产品各四根日线，并且都加入自选（图的范围就是自选）。"""

    sync_instruments(
        [
            InstrumentRef(
                inst_id=inst_id,
                inst_type="SPOT",
                base_ccy=f"X{product}",
                quote_ccy="USDT",
                state="live",
                inst_category="3",
                tick_size=Decimal("0.01"),
                lot_size=Decimal("0.00001"),
                min_size=Decimal("0.01"),
                list_time=START,
            )
            for product, (inst_id, _) in CLOSES.items()
        ]
    )
    for inst_id, closes in CLOSES.values():
        _write_daily(inst_id, closes)
        assert add_item(inst_id) is not None
    return client


def _graph(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.get("/api/relations/graph", params={**QUERY, **overrides})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def test_graph_returns_the_expected_network(network: TestClient) -> None:
    """节点、边、指标与社区逐项对上 fixture 的手算值。"""

    body = _graph(network)

    assert body["bar"] == BAR
    assert body["window"] == WINDOW
    assert body["min_abs_corr"] == "0.5"
    assert body["as_of"] == "2026-11-04T16:00:00Z"
    assert body["average_degree"] == "1.5"

    nodes = {node["product_key"]: node for node in body["nodes"]}
    assert list(nodes) == ["AAPL", "MSFT", "NVDA", "TSLA"]
    assert [nodes[key]["degree"] for key in nodes] == [2, 2, 2, 0]
    assert [nodes[key]["centrality"] for key in nodes] == ["0.6667", "0.6667", "0.6667", "0"]
    assert {node["asset_type"] for node in body["nodes"]} == {"tokenized_equity"}

    edges = [
        (edge["product_key_a"], edge["product_key_b"], edge["coefficient"], edge["samples"])
        for edge in body["edges"]
    ]
    assert edges == [
        ("AAPL", "MSFT", "-0.8", 4),
        ("AAPL", "NVDA", "1", 4),
        ("MSFT", "NVDA", "-0.8", 4),
    ]

    communities = [(row["community_id"], row["product_keys"]) for row in body["communities"]]
    assert communities == [(0, ["AAPL", "NVDA"]), (1, ["MSFT"]), (2, ["TSLA"])]


def test_every_edge_respects_threshold_and_has_both_ends(network: TestClient) -> None:
    """AC：每条边 |系数| ≥ 阈值、无自环、两端都在 nodes 里。"""

    body = _graph(network, min_abs_corr=0.5)

    keys = {node["product_key"] for node in body["nodes"]}
    for edge in body["edges"]:
        assert abs(Decimal(edge["coefficient"])) >= Decimal("0.5")
        assert edge["product_key_a"] != edge["product_key_b"]
        assert edge["product_key_a"] in keys
        assert edge["product_key_b"] in keys
    assert sum(node["degree"] for node in body["nodes"]) == 2 * len(body["edges"])


def test_higher_threshold_drops_the_weaker_edges(network: TestClient) -> None:
    """阈值 0.9 时只剩 AAPL-NVDA 那条 1.0 的边，其余节点变成孤立点。"""

    body = _graph(network, min_abs_corr=0.9)

    assert [(edge["product_key_a"], edge["product_key_b"]) for edge in body["edges"]] == [
        ("AAPL", "NVDA")
    ]
    nodes = {node["product_key"]: node for node in body["nodes"]}
    assert [nodes[key]["degree"] for key in nodes] == [1, 0, 1, 0]
    assert body["average_degree"] == "0.5"


def test_same_as_of_returns_identical_json(network: TestClient) -> None:
    """同一个 `as_of` 两次请求逐字节相同（系数、社区、顺序都不抖动）。"""

    first = network.get("/api/relations/graph", params={**QUERY, "as_of": "2026-11-04T16:00:00Z"})
    second = network.get("/api/relations/graph", params={**QUERY, "as_of": "2026-11-04T16:00:00Z"})

    assert first.status_code == 200
    assert first.text == second.text


def test_default_as_of_is_the_last_stored_bar(network: TestClient) -> None:
    """不给 `as_of` 时以库里最后一根 K 线为锚，因此两次请求也完全一致。"""

    first = network.get("/api/relations/graph", params=QUERY)
    second = network.get("/api/relations/graph", params=QUERY)

    assert first.status_code == 200
    assert first.json()["as_of"] == "2026-11-04T16:00:00Z"
    assert first.text == second.text


def test_earlier_as_of_sees_fewer_bars(network: TestClient) -> None:
    """`as_of` 只回看该时刻之前的样本：只留两根时相关系数未定义，一条边都画不出来。"""

    body = _graph(network, as_of="2026-11-02T16:00:00Z")

    assert body["edges"] == []
    assert body["average_degree"] == "0"


def test_decimal_and_time_shapes(network: TestClient) -> None:
    """系数与指标都是十进制字符串，时间带 `Z`。"""

    body = _graph(network)

    assert UTC_ZULU.match(body["as_of"]) is not None
    for edge in body["edges"]:
        assert DECIMAL.match(edge["coefficient"]) is not None
    for node in body["nodes"]:
        assert DECIMAL.match(node["centrality"]) is not None
    assert DECIMAL.match(body["average_degree"]) is not None


def test_neighbors_are_sorted_by_absolute_coefficient(network: TestClient) -> None:
    """AAPL 的两个邻居按 |系数| 从大到小：NVDA 1.0 在前，MSFT -0.8 在后。"""

    response = network.get(
        "/api/relations/neighbors",
        params={"product_key": "AAPL", "bar": BAR, "window": WINDOW, "min_abs_corr": 0.5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["product_key"] == "AAPL"
    assert body["items"] == [
        {
            "product_key": "NVDA",
            "asset_type": "tokenized_equity",
            "coefficient": "1",
            "samples": 4,
        },
        {
            "product_key": "MSFT",
            "asset_type": "tokenized_equity",
            "coefficient": "-0.8",
            "samples": 4,
        },
    ]


def test_neighbors_of_an_isolated_product_is_empty(network: TestClient) -> None:
    """TSLA 在自选里但没有任何过阈值的邻居：返回空列表，不是 404。"""

    response = network.get(
        "/api/relations/neighbors",
        params={"product_key": "TSLA", "bar": BAR, "window": WINDOW},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_neighbors_of_unknown_product_is_404(network: TestClient) -> None:
    """库里没有的产品按不存在处理。"""

    response = network.get(
        "/api/relations/neighbors",
        params={"product_key": "NOPE", "bar": BAR, "window": WINDOW},
    )

    assert response.status_code == 404
    assert "NOPE" in response.json()["detail"]


def test_empty_watchlist_gives_an_empty_graph(client: TestClient) -> None:
    """没有跟踪任何标的时图是空的：不拿全市场标的凑一张图。"""

    response = client.get("/api/relations/graph", params=QUERY)

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["communities"] == []
    assert body["average_degree"] == "0"


def test_window_below_two_is_rejected(network: TestClient) -> None:
    """窗口下界由契约定死：1 及以下直接 422。"""

    response = network.get("/api/relations/graph", params={**QUERY, "window": 1})

    assert response.status_code == 422
