"""策略 API：模板目录、实例增删改查与启停、目标组合回放。

数据全部走业务写入路径（`sync_instruments` + `upsert_candles`），不手写响应形状；
断言只针对可以从请求与库里复算出来的值。行情用两个加密现货标的：加密资产全天候
交易，回放时每个时点解析出的来源恒定，用例因此不依赖美股时段。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import strategy as strategy_routes
from app.api.schemas.common import DECIMAL_PATTERN
from app.core import Bar, Timeframe
from app.db import session_scope
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.strategy import (
    MAX_REPLAY_POINTS,
    ReplayOutcome,
    StrategyReplayRow,
    StrategyTemplateRow,
    evaluate_replay,
    get_instance,
)
from tests.factories.instruments import make_ref, make_swap_ref

DAY = timedelta(days=1)

# 判定时刻：2026-11-10 23:00 UTC。日线按 UTC+8 零点（16:00 UTC）定界的口径在这
# 里不重要——回放只看 open_time 与来源，加密资产的来源恒为 `okx_spot`。
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)

BTC_CLOSES = ["100", "101", "102", "103", "104", "105"]
ETH_CLOSES = ["50", "51", "52", "53", "55", "58"]

# 份额落在 [0.4, 0.6] **内部**的一组行情：两只标的的均值回归强度接近但不相等，长腿
# 权重因此是 0.45 左右的长小数，而不是被夹到 0.4 / 0.6 的有限小数。份额被夹到边界
# 的行情曾经掩盖了「权重 28 位小数超出契约 12 位」的缺陷。
MID_SHARE_CLOSES = ["56", "57", "58", "59.4", "60.1", "60.8"]

PAIR_PARAMS = {"reversion_window": 3, "strength_window": 2, "pair_count": 1}
SCALE = Decimal("0.000000001")


def seed_instruments(inst_ids: Sequence[str]) -> None:
    """按交换层的返回值写库；默认两只加密现货，按需追加同产品的永续。"""

    refs = []
    for inst_id in inst_ids:
        if inst_id.endswith("-SWAP"):
            refs.append(make_swap_ref(inst_id=inst_id, ct_val_ccy=inst_id.split("-")[0]))
        else:
            base = inst_id.split("-")[0]
            refs.append(make_ref(inst_id=inst_id, base_ccy=base, inst_category="1"))
    sync_instruments(refs)


def seed_daily(inst_id: str, closes: Sequence[str]) -> None:
    """写入连续日线（每天一根，最后一根落在 `AS_OF`）。

    来源取加密现货在任一时刻的有效来源 `okx_spot`：回放逐时点解析来源，写错来源
    会让它在每个时点都读不到行情（这本身就是来源治理的口径）。
    """

    opens = [AS_OF - DAY * (len(closes) - 1 - index) for index in range(len(closes))]
    upsert_candles(
        [
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse("1d"),
                open_time=open_time,
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("10"),
                confirm=True,
                source="okx_spot",
            )
            for open_time, close in zip(opens, closes, strict=True)
        ]
    )


@pytest.fixture()
def market(client: TestClient) -> TestClient:
    """两只走势相近但强度不同的加密现货，各六根日线。

    两列都单调上行（相关性足够配对），ETH 后段加速（均值回归与相对强弱读数不同），
    因此相对价值模板在这个区间上会选出一对多空腿。
    """

    seed_instruments(["BTC-USDT", "ETH-USDT"])
    seed_daily("BTC-USDT", BTC_CLOSES)
    seed_daily("ETH-USDT", ETH_CLOSES)
    return client


def create_pair_instance(client: TestClient, **overrides: object) -> dict[str, object]:
    """建一个相对价值实例；默认参数调到六根日线够用的窗口。"""

    payload: dict[str, object] = {
        "strategy_id": "relative_value",
        "name": "BTC/ETH 配对",
        "bar": "1d",
        "params": PAIR_PARAMS,
        "inst_ids": ["BTC-USDT", "ETH-USDT"],
    }
    payload.update(overrides)
    response = client.post("/api/strategy-instances", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def replay_window() -> dict[str, str]:
    """覆盖全部六根日线的区间。"""

    return {"start": "2026-11-05T00:00:00Z", "end": "2026-11-10T23:00:00Z"}


def test_catalog_lists_registered_templates(client: TestClient) -> None:
    """模板目录来自注册表：两个组合模板，参数表与模板 schema 一致。"""

    response = client.get("/api/strategies")
    assert response.status_code == 200, response.text
    body = response.json()

    identifiers = [item["strategy_id"] for item in body["items"]]
    assert identifiers == ["directional", "relative_value"]

    pair = next(item for item in body["items"] if item["strategy_id"] == "relative_value")
    assert pair["name"] == "相对价值组合"
    assert pair["version"]
    assert [param["name"] for param in pair["params"]] == [
        "reversion_window",
        "strength_window",
        "pair_count",
    ]
    window = pair["params"][0]
    assert window == {
        "name": "reversion_window",
        "title": "均值回归窗口",
        "kind": "int",
        "default": 20,
        "minimum": 2.0,
        "maximum": 500.0,
    }
    # 模板产出目标组合，不产出单标的动作，也不需要指标模块的序列。
    assert pair["required_indicators"] == []
    assert pair["emitted_actions"] == []
    assert pair["required_bars"] == ["1m", "5m", "15m", "1h", "4h", "1d"]


def test_create_instance_fills_template_defaults(market: TestClient) -> None:
    """建实例：参数补齐为完整参数表，阶段是草稿、启停默认打开。"""

    created = create_pair_instance(market, params={"reversion_window": 3}, name="  配对草稿  ")
    assert created["name"] == "配对草稿"
    assert created["strategy_id"] == "relative_value"
    assert created["strategy_version"] == "1.0.0"
    assert created["status"] == "strategy_generation"
    assert created["enabled"] is True
    assert created["execution_mode"] == "manual"
    assert created["latest_signal_at"] is None
    assert created["params"] == {
        "reversion_window": 3,
        "strength_window": 10,
        "pair_count": 1,
    }
    assert created["inst_ids"] == ["BTC-USDT", "ETH-USDT"]
    assert created["created_at"] == created["updated_at"]

    fetched = market.get(f"/api/strategy-instances/{created['instance_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    listed = market.get("/api/strategy-instances")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [item["instance_id"] for item in listed.json()["items"]] == [created["instance_id"]]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"strategy_id": "no_such_template"}, "未知的策略模板"),
        ({"params": {"reversion_window": 3, "unknown": 1}}, "不支持的参数"),
        ({"params": {"reversion_window": 0}}, "reversion_window"),
        ({"inst_ids": ["NOT-A-SYMBOL"]}, "未找到标的"),
    ],
)
def test_create_instance_rejects_invalid_payload(
    market: TestClient, payload: dict[str, object], reason: str
) -> None:
    """错误路径：未知模板、未知参数、越界参数、未知标的都返回 400。"""

    body = {"strategy_id": "relative_value", "name": "配对", "bar": "1d", "inst_ids": ["BTC-USDT"]}
    body.update(payload)
    response = market.post("/api/strategy-instances", json=body)
    assert response.status_code == 400, response.text
    assert reason in response.json()["detail"]


def test_create_instance_rejects_unknown_bar(market: TestClient) -> None:
    """周期取值由契约的 `Bar` 枚举把关：未知周期在请求边界就是 422。"""

    response = market.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "未知周期",
            "bar": "2h",
            "inst_ids": ["BTC-USDT"],
        },
    )
    assert response.status_code == 422, response.text


def test_create_instance_rejects_two_forms_of_one_product(market: TestClient) -> None:
    """同一个产品的现货与永续不能进同一个实例：视图按产品键组织，会互相覆盖。"""

    seed_instruments(["BTC-USDT-SWAP"])
    response = market.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "重复产品",
            "bar": "1d",
            "inst_ids": ["BTC-USDT", "BTC-USDT-SWAP"],
        },
    )
    assert response.status_code == 400, response.text
    assert "BTC" in response.json()["detail"]


def test_patch_merges_params_and_toggles_enabled(market: TestClient) -> None:
    """改参只覆盖提交的键；启停只改 `enabled`；生命周期阶段不接受 PATCH。"""

    created = create_pair_instance(market)
    instance_id = created["instance_id"]

    patched = market.patch(
        f"/api/strategy-instances/{instance_id}",
        json={"params": {"strength_window": 3}, "enabled": False},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["params"] == {
        "reversion_window": PAIR_PARAMS["reversion_window"],
        "strength_window": 3,
        "pair_count": 1,
    }
    assert body["enabled"] is False
    assert body["status"] == "strategy_generation"
    assert body["updated_at"] >= created["updated_at"]

    rejected = market.patch(
        f"/api/strategy-instances/{instance_id}",
        json={"status": "live_running"},
    )
    assert rejected.status_code == 422, rejected.text


def test_delete_instance_removes_it(market: TestClient) -> None:
    """删除之后读不到，再删一次是 404，回放记录随外键级联一起删掉。"""

    created = create_pair_instance(market)
    instance_id = created["instance_id"]
    replay_path = f"/api/strategy-instances/{instance_id}/replays"
    assert market.post(replay_path, json=replay_window()).status_code == 201

    assert market.delete(f"/api/strategy-instances/{instance_id}").status_code == 204
    assert market.get(f"/api/strategy-instances/{instance_id}").status_code == 404
    assert market.delete(f"/api/strategy-instances/{instance_id}").status_code == 404

    with session_scope() as session:
        remaining = session.scalars(
            select(StrategyReplayRow).where(StrategyReplayRow.instance_id == instance_id)
        ).all()
    assert list(remaining) == []


def test_catalog_rewrites_a_stale_template_row(market: TestClient) -> None:
    """模板升级分支：库里已有旧版本行时，列目录把它更新成注册表里的版本。

    这条分支曾经把已经是 epoch 整数的时刻又转一次 `datetime`，任何一次模板升级都会
    让目录接口 500——缺陷落在没有用例覆盖的分支上，因此这里直接构造「旧行」。
    """

    create_pair_instance(market)  # 先让投影落库

    with session_scope() as session:
        row = session.get(StrategyTemplateRow, "relative_value")
        assert row is not None
        stale = row.updated_at
        row.name = "旧名称"
        row.version = "0.9.0"
        row.summary = "旧说明"

    response = market.get("/api/strategies")
    assert response.status_code == 200, response.text
    projected = {item["strategy_id"]: item for item in response.json()["items"]}["relative_value"]
    assert projected["version"] != "0.9.0"

    with session_scope() as session:
        row = session.get(StrategyTemplateRow, "relative_value")
        assert row is not None
        assert (row.name, row.version, row.summary) == (
            projected["name"],
            projected["version"],
            projected["summary"],
        )
        assert row.updated_at >= stale


def test_replay_returns_target_portfolio_and_exposure_series(market: TestClient) -> None:
    """回放给出目标组合与逐点净敞口；规范化 JSON 的哈希与文本一致。"""

    created = create_pair_instance(market)
    response = market.post(
        f"/api/strategy-instances/{created['instance_id']}/replays",
        json=replay_window(),
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["instance_id"] == created["instance_id"]
    assert body["strategy_id"] == "relative_value"
    assert body["bar"] == "1d"

    legs = body["target"]["legs"]
    assert len(legs) == 2
    assert {leg["direction"] for leg in legs} == {"long", "short"}
    assert {leg["inst_id"] for leg in legs} == {"BTC-USDT", "ETH-USDT"}
    assert all(leg["inst_type"] == "SPOT" for leg in legs)
    assert all(leg["qty"] is None and leg["unit"] is None for leg in legs)

    long_weight = sum(Decimal(leg["target_weight"]) for leg in legs if leg["direction"] == "long")
    short_weight = sum(Decimal(leg["target_weight"]) for leg in legs if leg["direction"] == "short")
    assert abs((long_weight + short_weight) - Decimal(1)) <= SCALE
    assert Decimal(body["target"]["net_exposure"]) == long_weight - short_weight

    points = body["points"]
    assert len(points) == len(BTC_CLOSES)
    assert [point["as_of"] for point in points] == [
        "2026-11-05T23:00:00Z",
        "2026-11-06T23:00:00Z",
        "2026-11-07T23:00:00Z",
        "2026-11-08T23:00:00Z",
        "2026-11-09T23:00:00Z",
        "2026-11-10T23:00:00Z",
    ]
    # 每根 K 线追加一根，视图里的历史只会变长，腿数不会为负。
    assert all(point["leg_count"] >= 0 for point in points)

    canonical = body["canonical_json"]
    assert body["target_hash"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload = json.loads(canonical)
    assert [leg["product_key"] for leg in payload["legs"]] == ["BTC", "ETH"]
    assert payload["net_exposure"] == body["target"]["net_exposure"]


def test_replay_twice_is_reproducible_and_persisted(market: TestClient) -> None:
    """同一区间回放两次：目标组合的规范化 JSON 与哈希都相同，且两条记录都已落库。"""

    created = create_pair_instance(market)
    path = f"/api/strategy-instances/{created['instance_id']}/replays"

    first = market.post(path, json=replay_window())
    second = market.post(path, json=replay_window())
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["canonical_json"] == second.json()["canonical_json"]
    assert first.json()["target_hash"] == second.json()["target_hash"]
    assert first.json()["replay_id"] != second.json()["replay_id"]

    listed = market.get(path)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 2
    assert {item["target_hash"] for item in listed.json()["items"]} == {first.json()["target_hash"]}


def test_replay_disabled_instance_returns_409(market: TestClient) -> None:
    """停用的实例回放报冲突，不静默返回空结果。"""

    created = create_pair_instance(market)
    instance_id = created["instance_id"]
    market.patch(f"/api/strategy-instances/{instance_id}", json={"enabled": False})

    response = market.post(f"/api/strategy-instances/{instance_id}/replays", json=replay_window())
    assert response.status_code == 409, response.text
    assert "停用" in response.json()["detail"]


def test_replay_unknown_instance_returns_404(market: TestClient) -> None:
    assert (
        market.post("/api/strategy-instances/si_missing/replays", json=replay_window()).status_code
        == 404
    )
    assert market.get("/api/strategy-instances/si_missing/replays").status_code == 404


def test_replay_without_candles_returns_503(client: TestClient) -> None:
    """本地还没有该标的的行情：503 说明「先同步行情」，不是 400 或空结果。"""

    seed_instruments(["SOL-USDT"])
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "directional",
            "name": "只有标的没有行情",
            "bar": "1d",
            "inst_ids": ["SOL-USDT"],
        },
    ).json()

    response = client.post(
        f"/api/strategy-instances/{created['instance_id']}/replays",
        json=replay_window(),
    )
    assert response.status_code == 503, response.text
    assert "K 线" in response.json()["detail"]


def test_replay_rejects_inverted_window(market: TestClient) -> None:
    """区间起点不早于终点：400，不静默返回空曲线。"""

    created = create_pair_instance(market)
    response = market.post(
        f"/api/strategy-instances/{created['instance_id']}/replays",
        json={"start": "2026-11-10T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
    )
    assert response.status_code == 400, response.text


def test_evaluate_replay_is_deterministic_without_persisting(market: TestClient) -> None:
    """同一份库上重复计算同一区间：规范化 JSON 与哈希都不变，且计算本身不写库。"""

    created = create_pair_instance(market)
    instance = get_instance(created["instance_id"])
    assert instance is not None

    start = datetime(2026, 11, 5, tzinfo=UTC)
    end = datetime(2026, 11, 10, 23, tzinfo=UTC)
    first: ReplayOutcome = evaluate_replay(instance, start=start, end=end)
    second: ReplayOutcome = evaluate_replay(instance, start=start, end=end)

    assert first.canonical_json == second.canonical_json
    assert first.target_hash == second.target_hash
    assert (
        market.get(f"/api/strategy-instances/{instance.instance_id}/replays").json()["total"] == 0
    )


def test_replay_rejects_more_points_than_the_cap(client: TestClient) -> None:
    """时点数超过上限：400 明确报错并给出处置方式，不进计算、不占住请求线程。"""

    closes = [str(100 + index) for index in range(MAX_REPLAY_POINTS + 1)]
    seed_instruments(["BTC-USDT"])
    seed_daily("BTC-USDT", closes)
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "directional",
            "name": "时点过多",
            "bar": "1d",
            "inst_ids": ["BTC-USDT"],
        },
    ).json()

    response = client.post(
        f"/api/strategy-instances/{created['instance_id']}/replays",
        json={
            "start": "2020-01-01T00:00:00Z",
            "end": "2026-11-10T23:00:00Z",
        },
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert str(MAX_REPLAY_POINTS + 1) in detail
    assert "上限" in detail


def test_replay_quantizes_long_weights_to_the_contract_scale(client: TestClient) -> None:
    """长小数权重必须收敛到契约允许的精度，响应、落库与规范化 JSON 用同一份数值。"""

    seed_instruments(["BTC-USDT", "ETH-USDT"])
    seed_daily("BTC-USDT", BTC_CLOSES)
    seed_daily("ETH-USDT", MID_SHARE_CLOSES)
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "中间份额",
            "bar": "1d",
            "params": PAIR_PARAMS,
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    ).json()
    path = f"/api/strategy-instances/{created['instance_id']}/replays"

    response = client.post(path, json=replay_window())
    assert response.status_code == 201, response.text
    body = response.json()

    legs = body["target"]["legs"]
    weights = [Decimal(leg["target_weight"]) for leg in legs]
    # 前提：份额没有被夹到边界，权重确实是长小数那一支。
    assert all(Decimal("0.4") < weight < Decimal("0.6") for weight in weights)
    for leg in legs:
        assert re.fullmatch(DECIMAL_PATTERN, leg["target_weight"]), leg["target_weight"]
    assert re.fullmatch(DECIMAL_PATTERN, body["target"]["net_exposure"])
    for point in body["points"]:
        assert re.fullmatch(DECIMAL_PATTERN, point["net_exposure"])

    long_weight = sum(
        weight for weight, leg in zip(weights, legs, strict=True) if leg["direction"] == "long"
    )
    short_weight = sum(
        weight for weight, leg in zip(weights, legs, strict=True) if leg["direction"] == "short"
    )
    assert abs((long_weight + short_weight) - Decimal(1)) <= SCALE
    assert Decimal(body["target"]["net_exposure"]) == long_weight - short_weight
    assert body["target_hash"] == hashlib.sha256(body["canonical_json"].encode("utf-8")).hexdigest()

    # 响应与规范化 JSON 是同一份精度：逐个产品键比对权重字符串。
    inst_by_product = {"BTC": "BTC-USDT", "ETH": "ETH-USDT"}
    canonical = json.loads(body["canonical_json"])
    for canonical_leg in canonical["legs"]:
        inst_id = inst_by_product[canonical_leg["product_key"]]
        matching = next(leg for leg in legs if leg["inst_id"] == inst_id)
        assert canonical_leg["target_weight"] == matching["target_weight"]

    # 落库后可读回：曾经这里会因为 28 位小数让历史接口一直 500。
    stored = client.get(path)
    assert stored.status_code == 200, stored.text
    assert stored.json()["total"] == 1
    assert stored.json()["items"][0] == body


def test_replay_writes_only_after_the_response_is_built(
    market: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约映射失败时不落库：否则一条读不出来的记录会让历史接口一直 500。"""

    created = create_pair_instance(market)
    instance_id = created["instance_id"]
    path = f"/api/strategy-instances/{instance_id}/replays"

    def boom(_record: object) -> None:
        raise RuntimeError("契约映射失败")

    monkeypatch.setattr(strategy_routes, "_replay", boom)
    with pytest.raises(RuntimeError):
        market.post(path, json=replay_window())
    monkeypatch.undo()

    with session_scope() as session:
        rows = session.scalars(
            select(StrategyReplayRow).where(StrategyReplayRow.instance_id == instance_id)
        ).all()
    assert list(rows) == []

    # 失败没有把实例弄坏：恢复后回放与历史读取都正常。
    assert market.post(path, json=replay_window()).status_code == 201
    assert market.get(path).json()["total"] == 1
