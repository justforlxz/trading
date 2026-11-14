"""标的详情聚合端点：字段完整性、缺数据降级与不可用周期。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.backtest.model import BacktestRunRow
from app.core import Bar, Timeframe
from app.db import session_scope
from app.market import upsert_candles
from app.strategy import create_strategy, link_backtest
from tests.api.conftest import latest_opens, seed_instruments
from tests.factories.instruments import make_ref, make_swap_ref

ANALYSIS_BARS = ("1d", "4h", "1h")


def seed_analysis_bars(
    inst_id: str,
    *,
    count: int = 80,
    start: str = "100",
    step: str = "0.5",
    source: str = "okx",
) -> None:
    """写一段收盘价逐根抬升、高低价拉开、成交量递增的已完结 K 线。"""

    first = Decimal(start)
    increment = Decimal(step)
    rows = []
    for index, open_time in enumerate(latest_opens(count)):
        close = first + increment * index
        rows.append(
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse("1d"),
                open_time=open_time,
                open=close - Decimal("0.2"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100") + index,
                confirm=True,
                source=source,
            )
        )
    upsert_candles(rows)


def seed_watchlist(client: TestClient, *inst_ids: str) -> None:
    for inst_id in inst_ids:
        response = client.post("/api/watchlist", json={"inst_id": inst_id})
        assert response.status_code == 201, response.text


def add_backtest_run(inst_id: str) -> tuple[str, str, str]:
    """写一条已完成且正式关联到策略版本的回测行。"""

    run_id = "bt_detail_0001"
    created = datetime.now(UTC).replace(microsecond=0)
    strategy = create_strategy(
        name="AAPL 趋势",
        category="directional",
        description=None,
        timeframe="1d",
        direction="long_only",
        rule_json={
            "entry": {"all": [{"left": "MA(20)", "op": ">", "right": "MA(60)"}]},
            "exit": {"any": [{"left": "MA(20)", "op": "<", "right": "MA(60)"}]},
        },
        parameters={"trend_window": 20, "momentum_window": 10, "leg_count": 1},
        instrument_ids=[inst_id],
        cost_model=None,
        position_sizing=None,
        change_note="初始版本",
    )
    metrics = {
        "total_return": "0.124055",
        "max_drawdown": "0.0612",
        "trade_count": "37",
    }
    portfolio = {
        "net_exposure": "0",
        "leg_win_rate": {},
        "long_pnl": "0",
        "short_pnl": "0",
    }
    with session_scope() as session:
        session.add(
            BacktestRunRow(
                run_id=run_id,
                strategy_instance_id=strategy.current_version_id,
                strategy_id=strategy.id,
                strategy_version="1",
                params_json=json.dumps({"fast": 5, "slow": 20}),
                bar="1d",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 11, 1),
                data_source="okx",
                inst_id=inst_id,
                inst_type="SPOT",
                request_json=json.dumps({}),
                data_fingerprint="0" * 64,
                execution_model="next_open",
                costs_json=json.dumps({"fee_rate": "0.001"}),
                metrics_json=json.dumps(metrics),
                portfolio_json=json.dumps(portfolio),
                funding_total=Decimal("0"),
                result_hash="1" * 64,
                created_at=int(created.timestamp()),
            )
        )
    assert link_backtest(strategy.current_version_id, run_id) is True
    return run_id, strategy.current_version_id, strategy.id


def test_daily_analysis_returns_every_aggregate_field(client: TestClient) -> None:
    """一根完整的日线序列要同时给出报价、K 线、指标、价位、相关性与覆盖。"""

    seed_instruments(
        make_ref(),
        make_ref(inst_id="XQQQ-USDT", base_ccy="XQQQ"),
        make_ref(inst_id="XTSLA-USDT", base_ccy="XTSLA"),
    )
    seed_analysis_bars("XAAPL-USDT")
    seed_analysis_bars("XQQQ-USDT", start="400", step="1")
    seed_analysis_bars("XTSLA-USDT", start="250", step="0.4")
    seed_watchlist(client, "XAAPL-USDT", "XQQQ-USDT", "XTSLA-USDT")

    response = client.get("/api/instruments/XAAPL-USDT/analysis", params={"bar": "1d"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bar"] == "1d"
    assert body["instrument"]["inst_id"] == "XAAPL-USDT"

    quote = body["quote"]
    assert quote["last"]["price"] == "139.5"
    assert quote["last"]["change"] == "0.5"
    assert abs(
        Decimal(quote["last"]["change_pct"]) - Decimal("0.5") / Decimal("139") * 100
    ) < Decimal("0.000000001")
    assert quote["mark"] is None
    assert quote["index"] is None

    candles = body["candles"]
    assert len(candles["candles"]) == 80
    assert candles["data_source"] == "okx"
    assert [overlay["name"] for overlay in candles["overlays"]] == ["MA20", "MA60"]
    assert len(candles["overlays"][0]["points"]) == 61
    assert len(candles["overlays"][1]["points"]) == 21
    assert candles["available_from"] is not None
    assert candles["available_to"] is not None

    indicators = body["indicators"]
    assert indicators["trend"]["close"] == "139.5"
    assert Decimal(indicators["trend"]["ma20"]) > 0
    assert Decimal(indicators["trend"]["ma60"]) > 0
    assert Decimal(indicators["trend"]["price_vs_ma20_pct"]) > 0
    assert indicators["trend"]["slope_window"] == 5
    assert indicators["momentum"]["rsi14"] is not None
    assert indicators["momentum"]["macd"] is not None
    assert indicators["volatility"]["atr14"] is not None
    assert Decimal(indicators["volatility"]["atr_pct"]) > 0
    assert indicators["volume"]["current"] == "179"
    assert Decimal(indicators["volume"]["average20"]) > 0
    assert Decimal(indicators["volume"]["relative"]) > 0
    assert indicators["relative_strength"]["benchmark_inst_id"] == "XQQQ-USDT"
    assert Decimal(indicators["relative_strength"]["excess_return_pct"]) > 0

    levels = body["levels"]
    assert levels["window"] == 20
    assert levels["high20"] == "140.5"
    assert levels["low20"] == "129"
    assert Decimal(levels["high_distance_pct"]) > 0
    assert Decimal(levels["low_distance_pct"]) < 0

    correlations = body["correlations"]
    benchmark = next(row for row in correlations if row["role"] == "benchmark")
    assert benchmark["inst_id"] == "XQQQ-USDT"
    assert benchmark["window"] == 60
    assert benchmark["sample_size"] == 60
    assert benchmark["coefficient"] is not None
    assert benchmark["window_start"] is not None
    related = [row for row in correlations if row["role"] == "related"]
    assert [row["inst_id"] for row in related] == ["XTSLA-USDT"]

    coverage = {row["bar"]: row for row in body["coverage"]}
    assert set(coverage) == set(ANALYSIS_BARS)
    assert coverage["1d"]["available"] is True
    assert coverage["1d"]["candle_count"] == 80
    assert coverage["1d"]["gap_count"] >= 0
    assert coverage["1d"]["last_synced_at"] is not None
    for bar in ("4h", "1h"):
        assert coverage[bar]["available"] is False
        assert coverage[bar]["unavailable_reason"] == "尚未同步"
        assert coverage[bar]["candle_count"] == 0
        assert coverage[bar]["last_synced_at"] is None

    readings = indicators["readings"]
    assert 2 <= len(readings) <= 3
    assert all(any(char.isdigit() for char in sentence) for sentence in readings)
    assert not any("买入" in sentence or "卖出" in sentence for sentence in readings)


def test_available_periods_follow_backend_coverage(client: TestClient) -> None:
    """4 小时与 1 小时没有数据时，请求这两个周期只得到空 K 线与禁用原因。"""

    seed_instruments(make_ref())
    seed_analysis_bars("XAAPL-USDT")

    response = client.get("/api/instruments/XAAPL-USDT/analysis", params={"bar": "4h"})

    assert response.status_code == 200
    body = response.json()
    assert body["bar"] == "4h"
    assert body["candles"]["candles"] == []
    assert all(overlay["points"] == [] for overlay in body["candles"]["overlays"])
    coverage = {row["bar"]: row for row in body["coverage"]}
    assert coverage["4h"]["available"] is False
    assert coverage["4h"]["unavailable_reason"] == "尚未同步"


def test_instrument_without_candles_degrades_to_null_not_zero(client: TestClient) -> None:
    """已登记但没有任何行情时，价格与指标是 null，覆盖写尚未同步。"""

    seed_instruments(make_ref(inst_id="XETH-USDT", base_ccy="XETH"))

    response = client.get("/api/instruments/XETH-USDT/analysis", params={"bar": "1d"})

    assert response.status_code == 200
    body = response.json()
    assert body["quote"] == {"last": None, "mark": None, "index": None}
    assert body["candles"]["candles"] == []
    assert body["candles"]["available_from"] is None
    assert body["candles"]["available_to"] is None
    assert all(overlay["points"] == [] for overlay in body["candles"]["overlays"])
    assert body["indicators"]["trend"]["close"] is None
    assert body["indicators"]["trend"]["ma20"] is None
    assert body["indicators"]["momentum"]["rsi14"] is None
    assert body["indicators"]["volume"]["current"] is None
    assert body["levels"]["high20"] is None
    assert body["correlations"] == []
    for row in body["coverage"]:
        assert row["available"] is False
        assert row["unavailable_reason"] == "尚未同步"
        assert row["candle_count"] == 0
        assert row["last_synced_at"] is None
    assert body["indicators"]["readings"] == ["该周期尚未同步，无法生成指标解释。"]


def test_partial_history_disables_the_period_with_the_real_count(client: TestClient) -> None:
    """K 线不足 61 根时周期禁用，原因里写真实根数，不把不足当成零。"""

    seed_instruments(make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"))
    seed_analysis_bars("XMSFT-USDT", count=30)

    response = client.get("/api/instruments/XMSFT-USDT/analysis", params={"bar": "1d"})

    assert response.status_code == 200
    coverage = {row["bar"]: row for row in response.json()["coverage"]}
    assert coverage["1d"]["available"] is False
    assert coverage["1d"]["candle_count"] == 30
    assert "30" in coverage["1d"]["unavailable_reason"]


def test_unknown_instrument_is_404(client: TestClient) -> None:
    response = client.get("/api/instruments/NOPE-USDT/analysis")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_invalid_bar_is_422(client: TestClient) -> None:
    seed_instruments(make_ref())

    response = client.get("/api/instruments/XAAPL-USDT/analysis", params={"bar": "5m"})

    assert response.status_code == 422


def test_linked_strategies_come_from_saved_backtest_runs(client: TestClient) -> None:
    """最近 30 天内该标的的回测按行返回，收益与回撤换写成百分数。"""

    seed_instruments(make_ref())
    seed_analysis_bars("XAAPL-USDT")
    run_id, version_id, strategy_id = add_backtest_run("XAAPL-USDT")

    response = client.get("/api/instruments/XAAPL-USDT/analysis")

    assert response.status_code == 200
    linked = response.json()["linked_strategies"]
    assert len(linked) == 1
    assert linked[0]["run_id"] == run_id
    assert linked[0]["strategy_id"] == strategy_id
    assert linked[0]["strategy_version_id"] == version_id
    assert linked[0]["strategy_name"] == "AAPL 趋势"
    assert linked[0]["total_return_pct"] == "12.4055"
    assert linked[0]["max_drawdown_pct"] == "6.12"
    assert linked[0]["trade_count"] == 37
    assert linked[0]["backtest_start_date"] == "2026-10-01"


def test_runs_outside_the_month_are_not_linkable(client: TestClient) -> None:
    """超过 30 天的回测不进入关联策略，避免把旧结果当成当前分析依据。"""

    seed_instruments(make_ref())
    seed_analysis_bars("XAAPL-USDT")
    add_backtest_run("XAAPL-USDT")
    old = int((datetime.now(UTC) - timedelta(days=31)).timestamp())
    with session_scope() as session:
        row = session.get(BacktestRunRow, "bt_detail_0001")
        assert row is not None
        row.created_at = old

    response = client.get("/api/instruments/XAAPL-USDT/analysis")

    assert response.status_code == 200
    assert response.json()["linked_strategies"] == []


def test_benchmark_prefers_the_same_quote_currency(client: TestClient) -> None:
    """同一产品有多个报价币种时，基准必须与标的同报价，不能先到先得。"""

    seed_instruments(
        make_ref(inst_id="XQQQ-USDC", base_ccy="XQQQ", quote_ccy="USDC"),
        make_ref(inst_id="XQQQ-USDT", base_ccy="XQQQ"),
        make_ref(),
    )
    seed_analysis_bars("XAAPL-USDT")
    seed_analysis_bars("XQQQ-USDC", start="400", step="1")
    seed_analysis_bars("XQQQ-USDT", start="400", step="1")

    response = client.get("/api/instruments/XAAPL-USDT/analysis", params={"bar": "1d"})

    assert response.status_code == 200, response.text
    assert response.json()["indicators"]["relative_strength"]["benchmark_inst_id"] == "XQQQ-USDT"


@pytest.mark.parametrize("count", [1, 13, 14])
def test_short_history_does_not_break_the_endpoint(client: TestClient, count: int) -> None:
    """样本不足 14 根时 ATR 还没有成形，接口仍要正常降级而不是 500。"""

    seed_instruments(make_ref(inst_id="XNEW-USDT", base_ccy="XNEW"))
    seed_analysis_bars("XNEW-USDT", count=count)

    response = client.get("/api/instruments/XNEW-USDT/analysis", params={"bar": "1d"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["quote"]["last"] is not None
    assert len(body["candles"]["candles"]) == count
    if count < 14:
        assert body["indicators"]["volatility"]["atr14"] is None
        assert body["indicators"]["volatility"]["atr_pct"] is None
        assert body["indicators"]["volatility"]["atr_pct_avg20"] is None
    else:
        assert body["indicators"]["volatility"]["atr14"] is not None
        assert body["indicators"]["volatility"]["atr_pct_avg20"] is not None
    coverage = {row["bar"]: row for row in body["coverage"]}
    assert coverage["1d"]["available"] is False
    assert coverage["1d"]["candle_count"] == count


def test_instrument_is_never_used_as_its_own_benchmark(client: TestClient) -> None:
    """BTC 只有同产品标的时，基准必须留空，不能把自身当成基准算出 0 超额。"""

    seed_instruments(
        make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
        make_swap_ref(
            inst_id="BTC-USDT-SWAP",
            inst_category="1",
            ct_val_ccy="BTC",
            settle_ccy="USDT",
            base_ccy="BTC",
            quote_ccy="USDT",
        ),
    )
    seed_analysis_bars("BTC-USDT")

    response = client.get("/api/instruments/BTC-USDT/analysis", params={"bar": "1d"})

    assert response.status_code == 200, response.text
    body = response.json()
    relative = body["indicators"]["relative_strength"]
    assert relative["benchmark_inst_id"] is None
    assert relative["symbol_return_pct"] is None
    assert relative["benchmark_return_pct"] is None
    assert relative["excess_return_pct"] is None
    assert all(row["inst_id"] != "BTC-USDT" for row in body["correlations"])
