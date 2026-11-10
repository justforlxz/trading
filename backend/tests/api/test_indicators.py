"""指标端点：目录形状、四个周期各一条通过用例、参数通道与全部错误路径。

K 线只经 `app.market` 的写入路径落库（已收盘），断言的是接口契约而不是上游
原始结构：响应字段集合必须与 `app/api/schemas/indicators.py` 完全一致。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.core import Bar, Timeframe
from app.indicators import list_definitions
from app.market import upsert_candles
from app.shared import bar_seconds
from tests.api.conftest import seed_instruments
from tests.factories.instruments import make_ref

DECIMAL = re.compile(r"^-?\d{1,20}(\.\d{1,12})?$")
UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# 闸门要求的四个周期；`1m` / `5m` 不单独造用例。
GATE_BARS = ("15m", "1h", "4h", "1d")
SEEDED_BARS = 40
NO_DATA_INST = "XETH-USDT"


def aligned_newest(bar: str) -> datetime:
    """当前时刻向下对齐到该周期的开盘边界（与写入路径的时间轴一致）。"""

    step = bar_seconds(bar)
    now = int(datetime.now(UTC).timestamp())
    return datetime.fromtimestamp(now - now % step, tz=UTC)


def seed_series(inst_id: str, bar: str, count: int = SEEDED_BARS) -> None:
    """写一条单调上涨的已收盘 K 线序列，指标值随周期确定性变化。"""

    step = timedelta(seconds=bar_seconds(bar))
    newest = aligned_newest(bar)
    rows = [
        Bar(
            inst_id=inst_id,
            timeframe=Timeframe.parse(bar),
            open_time=newest - step * (count - 1 - index),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=Decimal(10 + index),
            confirm=True,
            source="okx",
        )
        for index in range(count)
    ]
    upsert_candles(rows)


def seed_oscillating(inst_id: str, bar: str, count: int = SEEDED_BARS) -> None:
    """涨跌交替的已收盘 K 线，让 RSI 这类比值指标算出无限小数。"""

    step = timedelta(seconds=bar_seconds(bar))
    newest = aligned_newest(bar)
    price = Decimal("100")
    rows = []
    for index in range(count):
        if index:
            price += Decimal("2") if index % 2 else Decimal("-1")
        rows.append(
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse(bar),
                open_time=newest - step * (count - 1 - index),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal(10 + index),
                confirm=True,
                source="okx",
            )
        )
    upsert_candles(rows)


@pytest.fixture
def indicator_data(client: TestClient) -> TestClient:
    """一个有四个周期 K 线的现货标的，以及一个同步过但没有 K 线的标的。"""

    seed_instruments(make_ref(), make_ref(inst_id=NO_DATA_INST, base_ccy="XETH"))
    for bar in GATE_BARS:
        seed_series("XAAPL-USDT", bar)
    return client


def get_series(
    client: TestClient,
    *,
    inst_id: str = "XAAPL-USDT",
    bar: str = "1h",
    names: str = "sma,rsi",
    **extra: str,
) -> Response:
    return client.get(
        "/api/indicators/series",
        params={"inst_id": inst_id, "bar": bar, "names": names, **extra},
    )


# ---------------------------------------------------------------- catalog


def test_catalog_is_generated_from_registry(client: TestClient) -> None:
    """目录逐条来自注册表，字段集合与契约模型一致（min_length → min_bars）。"""

    response = client.get("/api/indicators")

    assert response.status_code == 200
    items = response.json()["items"]
    expected = list_definitions()
    assert [item["name"] for item in items] == [row.name for row in expected]
    assert len(items) == 8

    for item in items:
        assert set(item) == {"name", "title", "summary", "params", "outputs", "min_bars"}
        for spec in item["params"]:
            assert set(spec) == {"name", "title", "kind", "default", "minimum", "maximum"}

    rsi = next(item for item in items if item["name"] == "rsi")
    assert rsi["min_bars"] == 15
    assert rsi["outputs"] == ["rsi"]
    assert rsi["params"][0]["name"] == "period"
    assert rsi["params"][0]["kind"] == "int"


def test_catalog_unknown_subpath_is_not_found(client: TestClient) -> None:
    """目录只发布两个端点，别的子路径按不存在处理，不回落到桩。"""

    response = client.get("/api/indicators/nope")

    assert response.status_code == 404
    assert response.json()["detail"]


# ---------------------------------------------------------------- series


@pytest.mark.parametrize("bar", GATE_BARS)
def test_series_covers_each_gate_timeframe(indicator_data: TestClient, bar: str) -> None:
    """15m / 1h / 4h / 1d 都能取到序列，且只返回契约字段。"""

    response = get_series(indicator_data, bar=bar)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"inst_id", "inst_type", "bar", "series"}
    assert (body["inst_id"], body["inst_type"], body["bar"]) == ("XAAPL-USDT", "SPOT", bar)

    series = body["series"]
    assert [item["name"] for item in series] == ["sma", "rsi"]
    outputs = {"sma": ["sma"], "rsi": ["rsi"]}
    for item in series:
        assert set(item) == {"name", "params", "points"}
        assert item["points"]
        last = item["points"][-1]
        assert set(last) == {"time", "values"}
        assert UTC_ZULU.match(last["time"]) is not None
        assert set(last["values"]) == set(outputs[item["name"]])
        for value in last["values"].values():
            assert value is not None
            assert DECIMAL.match(value) is not None


def test_series_values_fit_decimal_contract(client: TestClient) -> None:
    """无限小数的指标值也必须落在 Decimal 字符串契约内（最多 12 位小数）。"""

    seed_instruments(make_ref())
    seed_oscillating("XAAPL-USDT", "5m")

    response = get_series(client, bar="5m", names="rsi,macd,bollinger")

    assert response.status_code == 200
    series = response.json()["series"]
    for item in series:
        for point in item["points"]:
            for value in point["values"].values():
                assert value is None or DECIMAL.match(value) is not None

    # 66.666… 这类值必须真的被截到 12 位小数，否则用例没有覆盖到量化路径。
    decimals = [
        len(value.split(".")[1])
        for item in series
        for point in item["points"]
        for value in point["values"].values()
        if value is not None and "." in value
    ]
    assert max(decimals) == 12


def test_series_echoes_default_params(indicator_data: TestClient) -> None:
    """不给 params 时回显注册表默认值，调用方不必自己维护一份默认表。"""

    body = get_series(indicator_data, names="sma").json()

    assert body["series"][0]["params"] == {"period": 20}


def test_series_params_override_changes_values(indicator_data: TestClient) -> None:
    """params 覆盖后的回显与曲线取值都随参数变化。"""

    default = get_series(indicator_data, names="sma").json()["series"][0]
    overridden = get_series(indicator_data, names="sma", params='{"sma":{"period":5}}').json()[
        "series"
    ][0]

    assert overridden["params"] == {"period": 5}
    assert overridden["points"][-1]["values"]["sma"] != default["points"][-1]["values"]["sma"]
    # 两点都以同一根最新 K 线为终点：只换参数，不换输入窗口。
    assert overridden["points"][-1]["time"] == default["points"][-1]["time"]


def test_series_limit_keeps_only_tail(indicator_data: TestClient) -> None:
    """limit 只截取窗口尾部，最新一点与未截断时完全一致。"""

    full = get_series(indicator_data, names="sma").json()["series"][0]["points"]
    tail = get_series(indicator_data, names="sma", limit="30").json()["series"][0]["points"]

    assert len(tail) == 30
    assert tail[-1] == full[-1]


def test_series_without_candles_is_empty_not_fabricated(indicator_data: TestClient) -> None:
    """标的没有 K 线时返回空序列与默认参数，不补造数值。"""

    response = get_series(indicator_data, inst_id=NO_DATA_INST, names="sma")

    assert response.status_code == 200
    series = response.json()["series"][0]
    assert series["points"] == []
    assert series["params"] == {"period": 20}


def test_series_rejects_period_zero(indicator_data: TestClient) -> None:
    """参数越界（period=0）按 422 拒绝，不落到 500。"""

    response = get_series(indicator_data, names="rsi", params='{"rsi":{"period":0}}')

    assert response.status_code == 422
    assert "period" in response.json()["detail"]


def test_series_rejects_unknown_param(indicator_data: TestClient) -> None:
    """指标不认识的参数名同样是 422。"""

    response = get_series(indicator_data, names="sma", params='{"sma":{"window":5}}')

    assert response.status_code == 422
    assert response.json()["detail"]


def test_series_rejects_unknown_indicator(indicator_data: TestClient) -> None:
    """未登记的指标名由注册表拒绝，消息里列出已登记名字。"""

    response = get_series(indicator_data, names="sma,unknown")

    assert response.status_code == 422
    assert "unknown" in response.json()["detail"]


def test_series_rejects_unknown_bar(indicator_data: TestClient) -> None:
    """周期只认六个规范写法，`2h` 直接 422。"""

    response = get_series(indicator_data, bar="2h")

    assert response.status_code == 422


def test_series_rejects_malformed_params_json(indicator_data: TestClient) -> None:
    """params 不是合法 JSON 时 422，而不是 500。"""

    response = get_series(indicator_data, names="sma", params="{")

    assert response.status_code == 422
    assert "JSON" in response.json()["detail"]


def test_series_rejects_params_outside_requested_names(indicator_data: TestClient) -> None:
    """params 里出现未请求的指标属于调用方错误，不做静默忽略。"""

    response = get_series(indicator_data, names="sma", params='{"rsi":{"period":14}}')

    assert response.status_code == 422
    assert "rsi" in response.json()["detail"]


@pytest.mark.parametrize("names", ["", " , "])
def test_series_rejects_blank_names(indicator_data: TestClient, names: str) -> None:
    """names 去掉空白后为空时没有指标可算，按 422 拒绝。"""

    response = get_series(indicator_data, names=names)

    assert response.status_code == 422


@pytest.mark.parametrize("limit", ["0", "1001"])
def test_series_rejects_out_of_range_limit(indicator_data: TestClient, limit: str) -> None:
    """limit 契约是 1..1000，越界由查询参数校验拒绝。"""

    response = get_series(indicator_data, names="sma", limit=limit)

    assert response.status_code == 422


def test_series_unknown_instrument_is_not_found(indicator_data: TestClient) -> None:
    """未同步的标的按 404 处理，与 instruments 域口径一致。"""

    response = get_series(indicator_data, inst_id="NOPE-USDT")

    assert response.status_code == 404
    assert "NOPE-USDT" in response.json()["detail"]
