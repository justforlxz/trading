"""市场广度与共振：纯函数已知答案，横截面按类别分开、来源按标的各自解析。

纯函数部分用手算用例：涨跌家数、比值、窗口首尾定方向、样本不足给 `None`。
编排部分落库：每一类标的各自成组，代币化股票在美股交易时段读代理行情、休市时段
读 OKX 行情，两个横截面的参与标的不相混。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select

from app.core import Bar, Timeframe, ValidationError
from app.db import session_scope
from app.instrument import list_tradable, sync_instruments
from app.market import (
    MIN_RESONANCE_PARTICIPANTS,
    Candle,
    advance_decline,
    asset_session,
    market_overview,
    primary_source,
    resonance_strength,
    to_epoch,
    upsert_candles,
)
from tests.factories.instruments import make_ref, make_swap_ref

HOUR = timedelta(hours=1)
START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)

# 加密资产的日线开在 OKX 的 UTC+8 零点，即 16:00 UTC。
DAY_START = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
DAY = timedelta(days=1)
WINDOW_BARS = 21  # 共振窗口 20 根，加一根用来算窗口首尾

# 2026-11-10 15:00 UTC = 美东 10:00，正常交易时段；次日 02:00 UTC = 美东 21:00，休市。
REGULAR_MOMENT = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
CLOSED_MOMENT = datetime(2026, 11, 11, 2, 0, tzinfo=UTC)


def _bars(
    closes: list[float],
    *,
    symbol: str = "ATEST",
    source: str = "okx_spot",
    bar: str = "1h",
    start: datetime = START,
) -> list[Bar]:
    """一串只有收盘价有意义的 K 线，按 `start` 起逐个周期往后排。"""

    timeframe = Timeframe.parse(bar)
    step = HOUR if bar == "1h" else DAY
    return [
        Bar(
            inst_id=symbol,
            timeframe=timeframe,
            open_time=start + step * index,
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=Decimal("1"),
            confirm=True,
            source=source,
        )
        for index, close in enumerate(closes)
    ]


def _rising(count: int, *, step: float = 1.0) -> list[float]:
    return [10.0 + step * index for index in range(count)]


def _falling(count: int, *, step: float = 1.0) -> list[float]:
    return [100.0 - step * index for index in range(count)]


# ---------------------------------------------------------------- 涨跌家数


def test_ten_symbols_eight_up_two_down() -> None:
    """8 涨 2 跌：家数与比值都是手算值，参与标的 10 个。"""

    bars_by_symbol = {f"UP{index}": _bars([10.0, 11.0]) for index in range(8)} | {
        f"DOWN{index}": _bars([10.0, 9.0]) for index in range(2)
    }

    breadth = advance_decline(bars_by_symbol)

    assert breadth.advancers == 8
    assert breadth.decliners == 2
    assert breadth.unchanged == 0
    assert breadth.ratio == 4.0
    assert breadth.participants == 10


def test_flat_symbol_is_counted_as_unchanged() -> None:
    """收盘价没变的标的算「不变」，仍在参与标的里，不塞进上涨或下跌。"""

    breadth = advance_decline({"FLAT": _bars([10.0, 10.0]), "UP": _bars([1.0, 2.0])})

    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (1, 0, 1)
    assert breadth.participants == 2


def test_symbol_without_two_bars_is_not_a_participant() -> None:
    """一根 K 线定不了方向：不计入参与标的，也不补一个「不变」。"""

    breadth = advance_decline({"ONE": _bars([10.0]), "NONE": [], "UP": _bars([1.0, 2.0])})

    assert breadth.participants == 1
    assert breadth.advancers == 1


def test_no_decliner_means_no_ratio() -> None:
    """没有下跌标的时除法不成立：比值如实为 `None`，不写成无穷大。"""

    breadth = advance_decline({"A": _bars([1.0, 2.0]), "B": _bars([3.0, 4.0])})

    assert breadth.decliners == 0
    assert breadth.ratio is None


def test_empty_cross_section_is_all_zero() -> None:
    breadth = advance_decline({})

    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (0, 0, 0)
    assert breadth.ratio is None
    assert breadth.participants == 0


def test_input_order_does_not_decide_the_direction() -> None:
    """反序传入的 K 线仍按 `open_time` 判断方向，最后两根的顺序不可信。"""

    breadth = advance_decline({"A": list(reversed(_bars([10.0, 11.0])))})

    assert breadth.advancers == 1
    assert breadth.decliners == 0


# ---------------------------------------------------------------- 共振强度


def test_resonance_is_one_when_every_symbol_rises() -> None:
    """全部同向上涨：强度 1.0。"""

    bars_by_symbol = {
        f"UP{index}": _bars(_rising(WINDOW_BARS), symbol=f"UP{index}") for index in range(10)
    }

    resonance = resonance_strength(bars_by_symbol, 20)

    assert resonance.strength == 1.0
    assert resonance.participants == 10
    assert resonance.window == 20


def test_resonance_is_zero_when_half_rises_and_half_falls() -> None:
    """涨跌各半：强度 0.0。"""

    bars_by_symbol = {
        f"UP{index}": _bars(_rising(WINDOW_BARS), symbol=f"UP{index}") for index in range(5)
    } | {f"DOWN{index}": _bars(_falling(WINDOW_BARS), symbol=f"DOWN{index}") for index in range(5)}

    resonance = resonance_strength(bars_by_symbol, 20)

    assert resonance.strength == 0.0
    assert resonance.participants == 10


def test_resonance_needs_at_least_five_participants() -> None:
    """参与标的不足 5 个：不给数，参与数照实返回。"""

    assert MIN_RESONANCE_PARTICIPANTS == 5
    bars_by_symbol = {
        f"UP{index}": _bars(_rising(WINDOW_BARS), symbol=f"UP{index}")
        for index in range(MIN_RESONANCE_PARTICIPANTS - 1)
    }

    resonance = resonance_strength(bars_by_symbol, 20)

    assert resonance.strength is None
    assert resonance.participants == 4


def test_resonance_stays_within_zero_and_one() -> None:
    """7 涨 2 跌 1 平：强度 = |7-2| / 10 = 0.5，恒在 [0, 1]。"""

    bars_by_symbol = (
        {f"UP{index}": _bars(_rising(WINDOW_BARS), symbol=f"UP{index}") for index in range(7)}
        | {
            f"DOWN{index}": _bars(_falling(WINDOW_BARS), symbol=f"DOWN{index}")
            for index in range(2)
        }
        | {"FLAT": _bars([7.0] * WINDOW_BARS, symbol="FLAT")}
    )

    resonance = resonance_strength(bars_by_symbol, 20)

    assert resonance.participants == 10
    assert resonance.strength == pytest.approx(0.5, abs=1e-12)
    assert 0.0 <= resonance.strength <= 1.0


def test_resonance_only_looks_at_the_trailing_window() -> None:
    """同一段历史，窗口取 1 与取 3 得出不同的强度：窗口真的被用上了。"""

    # 四个标的在最后一根回落（3.0 → 2.0），窗口 3 的首尾却是上涨（1.0 → 2.0）。
    falling = {f"A{index}": _bars([1.0, 2.0, 3.0, 2.0], symbol=f"A{index}") for index in range(4)}
    rising = {"B": _bars([1.0, 2.0, 3.0, 4.0], symbol="B")}
    bars_by_symbol = falling | rising

    # 窗口 1：4 跌 1 涨 → |1-4| / 5 = 0.6；窗口 3：5 个都涨 → 1.0。
    assert resonance_strength(bars_by_symbol, 1).strength == pytest.approx(0.6, abs=1e-12)
    assert resonance_strength(bars_by_symbol, 3).strength == 1.0


def test_resonance_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValidationError):
        resonance_strength({"A": _bars([1.0, 2.0])}, 0)


def test_resonance_without_participants_gives_no_number() -> None:
    resonance = resonance_strength({}, 20)

    assert resonance.strength is None
    assert resonance.participants == 0
    assert resonance.window == 20


# ---------------------------------------------------------------- 横截面编排


def _names(prefix: str, count: int) -> list[str]:
    """一批互不相同的标的标识。"""

    return [f"{prefix}{index}" for index in range(count)]


def _crypto_spot(symbols: list[str], closes: list[float]) -> None:
    """登记这批加密现货并写入同一段日线；现货来源是 `okx_spot`。"""

    refs = [
        make_ref(inst_id=f"{symbol}-USDT", base_ccy=symbol, inst_category="1") for symbol in symbols
    ]
    sync_instruments(refs)
    for ref in refs:
        upsert_candles(
            _bars(closes, symbol=ref.inst_id, source="okx_spot", bar="1d", start=DAY_START)
        )


def _crypto_swap(symbols: list[str], closes: list[float]) -> None:
    """登记这批加密永续并写入同一段日线；永续来源是 `okx_swap`。"""

    refs = [
        make_swap_ref(
            inst_id=f"{symbol}-USDT-SWAP",
            ct_val_ccy=symbol,
            settle_ccy="USDT",
            inst_category="1",
        )
        for symbol in symbols
    ]
    sync_instruments(refs)
    for ref in refs:
        upsert_candles(
            _bars(closes, symbol=ref.inst_id, source="okx_swap", bar="1d", start=DAY_START)
        )


def _last_open() -> datetime:
    return DAY_START + DAY * (WINDOW_BARS - 1)


def test_overview_counts_each_class_on_its_own() -> None:
    """两类标的各自成组：现货 8 涨 2 跌、永续 2 涨 8 跌，互不混算。"""

    _crypto_spot(_names("CA", 8), _rising(WINDOW_BARS))
    _crypto_spot(_names("CD", 2), _falling(WINDOW_BARS))
    _crypto_swap(_names("SA", 2), _rising(WINDOW_BARS))
    _crypto_swap(_names("SD", 8), _falling(WINDOW_BARS))

    spot = market_overview(_last_open(), "1d", "SPOT")
    swap = market_overview(_last_open(), "1d", "SWAP")

    assert (spot.breadth.advancers, spot.breadth.decliners) == (8, 2)
    assert (swap.breadth.advancers, swap.breadth.decliners) == (2, 8)
    # 各自的参与标的数就是该类别可交易标的数。
    assert spot.breadth.participants == len(list_tradable("SPOT")) == 10
    assert swap.breadth.participants == len(list_tradable("SWAP")) == 10
    # 两类标的的标识集合不相交，横截面不会把同一批标的算两次。
    spot_symbols = {row.symbol for row in list_tradable("SPOT")}
    swap_symbols = {row.symbol for row in list_tradable("SWAP")}
    assert spot_symbols.isdisjoint(swap_symbols)

    assert spot.resonance.participants == spot.breadth.participants
    assert swap.resonance.participants == swap.breadth.participants
    assert spot.resonance.window == 20
    assert spot.bar == "1d"
    assert spot.as_of == _last_open()


def test_overview_always_reads_the_okx_source() -> None:
    """代币化股票在交易时段也读 OKX 行情，另一个来源的行不参与横截面。"""

    sync_instruments([make_ref(inst_id="XAAPL-USDT", base_ccy="XAAPL")])
    legacy_start = datetime(2026, 11, 8, 14, 30, tzinfo=UTC)
    okx_start = datetime(2026, 11, 8, 16, 0, tzinfo=UTC)
    upsert_candles(
        _bars(
            [10.0, 11.0, 12.0],
            symbol="XAAPL-USDT",
            source="okx_swap",
            bar="1d",
            start=legacy_start,
        )
    )
    upsert_candles(
        _bars([20.0, 19.0, 18.0], symbol="XAAPL-USDT", source="okx_spot", bar="1d", start=okx_start)
    )

    regular = market_overview(REGULAR_MOMENT, "1d", "SPOT")
    closed = market_overview(CLOSED_MOMENT, "1d", "SPOT")

    assert (regular.breadth.advancers, regular.breadth.decliners) == (0, 1)
    assert (closed.breadth.advancers, closed.breadth.decliners) == (0, 1)


def test_overview_excludes_bars_after_as_of() -> None:
    """`as_of` 之后的 K 线一根都不算：取到前一根时方向就是那个时点的方向。"""

    _crypto_spot(["ONLY"], [10.0, 11.0, 5.0])

    before_jump = market_overview(DAY_START + DAY, "1d", "SPOT")
    after_jump = market_overview(DAY_START + 2 * DAY, "1d", "SPOT")

    assert (before_jump.breadth.advancers, before_jump.breadth.decliners) == (1, 0)
    assert (after_jump.breadth.advancers, after_jump.breadth.decliners) == (0, 1)


def test_overview_rejects_a_naive_as_of() -> None:
    with pytest.raises(ValidationError):
        market_overview(datetime(2026, 11, 10, 0, 0), "1d", "SPOT")


def test_overview_of_an_empty_class_is_all_zero() -> None:
    overview = market_overview(_last_open(), "1d", "SWAP")

    assert overview.breadth.participants == 0
    assert overview.breadth.ratio is None
    assert overview.resonance.strength is None


# ---------------------------------------------------------------- 批量取数


def _per_symbol_bars(inst_type: str, bar: str, as_of: datetime, count: int) -> dict[str, list[Bar]]:
    """改前的取数口径：每个标的各发一条 SQL。批量取数的结果必须与它逐项相等。"""

    moment = to_epoch(as_of)
    loaded: dict[str, list[Bar]] = {}
    with session_scope() as session:
        for instrument in list_tradable(inst_type):
            session_state = asset_session(
                instrument.asset_type, as_of, inst_type=instrument.inst_type
            )
            source = primary_source(session_state, instrument.asset_type, instrument.inst_type)
            statement = (
                select(Candle)
                .where(
                    Candle.symbol == instrument.symbol,
                    Candle.bar == bar,
                    Candle.source == source,
                    Candle.open_time <= moment,
                )
                .order_by(Candle.open_time.desc())
                .limit(count)
            )
            rows = list(session.scalars(statement))
            if rows:
                loaded[instrument.symbol] = [row.to_bar() for row in reversed(rows)]
    return loaded


@contextmanager
def _count_statements() -> Iterator[list[str]]:
    """数一次编排发到库里的 SQL 条数；逐标的取数会留下「标的数」条，批量取数留下落组数条。"""

    issued: list[str] = []

    def _record(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        issued.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield issued
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


def _mixed_cross_section() -> None:
    """每种边界各占一个标的：窗口外的旧值、只有 1 根、一根都没有、两种来源、`as_of` 之后。"""

    # 30 根：前 9 根从 100 一路往下掉，最近 21 根上涨。窗口内首尾定方向是上涨；
    # 若把窗口外的旧值也读进来，方向会变成下跌——这条把「只取尾巴」钉住。
    _crypto_spot(
        ["LONG"],
        [100.0 - index for index in range(9)] + [10.0 + index for index in range(WINDOW_BARS)],
    )
    # 只有 1 根：定不了方向，不进参与标的，但取数时不能丢。
    _crypto_spot(["ONE"], [7.0])
    # 一根 K 线都没有：不进结果，也不报错。
    sync_instruments([make_ref(inst_id="NONE-USDT", base_ccy="NONE", inst_category="1")])
    # 同一标的两种来源都有数据：只算此刻有效的 `okx_spot`，另一来源的下跌不参与。
    sync_instruments([make_ref(inst_id="XMULTI-USDT", base_ccy="XMULTI", inst_category="1")])
    upsert_candles(
        _bars(
            _falling(WINDOW_BARS), symbol="XMULTI-USDT", source="yahoo", bar="1d", start=DAY_START
        )
    )
    upsert_candles(
        _bars([9.0, 9.5], symbol="XMULTI-USDT", source="okx_spot", bar="1d", start=DAY_START)
    )
    # 只在 `as_of` 之后才有 K 线：一根都不算。
    sync_instruments([make_ref(inst_id="FUTURE-USDT", base_ccy="FUTURE", inst_category="1")])
    upsert_candles(
        _bars([10.0, 5.0], symbol="FUTURE-USDT", source="okx_spot", bar="1d", start=_last_open())
    )


def test_batch_read_matches_the_per_symbol_read() -> None:
    """同一份数据：批量取数与逐标的取数给出完全相同的广度与共振（含各种边界）。"""

    _mixed_cross_section()
    as_of = _last_open()

    overview = market_overview(as_of, "1d", "SPOT")
    per_symbol = _per_symbol_bars("SPOT", "1d", as_of, WINDOW_BARS)

    assert overview.breadth == advance_decline(per_symbol)
    assert overview.resonance == resonance_strength(per_symbol, 20)


def test_batch_read_keeps_every_edge_case() -> None:
    """逐项钉住边界：参与标的只有 2 个，窗口外的旧值、另一来源与 `as_of` 之后都不算。"""

    _mixed_cross_section()

    breadth = market_overview(_last_open(), "1d", "SPOT").breadth

    # LONG 在窗口内上涨、XMULTI 的 `okx_spot` 序列 9.0 → 9.5 上涨；ONE 只有 1 根、
    # NONE 没有 K 线、FUTURE 的 K 线在 `as_of` 之后、XMULTI 的 `yahoo` 序列都不算。
    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (2, 0, 0)
    assert breadth.participants == 2
    assert breadth.ratio is None


def test_batch_read_statement_count_does_not_grow_with_the_cross_section() -> None:
    """标的从 10 个加到 50 个，SQL 条数不变：横截面取数只有一条 SQL。"""

    _crypto_spot(_names("CA", 10), _rising(WINDOW_BARS))
    with _count_statements() as few:
        market_overview(_last_open(), "1d", "SPOT")

    _crypto_spot(_names("CB", 40), _rising(WINDOW_BARS))
    with _count_statements() as many:
        market_overview(_last_open(), "1d", "SPOT")

    assert len(list_tradable("SPOT")) == 50
    assert len(many) == len(few)
    # 其余语句是标的名录与测试装配自己的 savepoint，不随标的数增长；
    # 横截面取数只有一条含 `candles` 的 SQL。
    assert len([statement for statement in many if "FROM candles" in statement]) == 1


# ---------------------------------------------------------------- 端点


def test_endpoint_returns_the_overview_as_the_contract_shapes_it(client: TestClient) -> None:
    """接口把比值写成定点字符串，窗口与参与数照实返回。"""

    _crypto_spot(_names("CA", 8), _rising(WINDOW_BARS))
    _crypto_spot(_names("CD", 2), _falling(WINDOW_BARS))

    response = client.get(
        "/api/market/breadth",
        params={"inst_type": "SPOT", "bar": "1d", "as_of": _last_open().isoformat()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["inst_type"] == "SPOT"
    assert body["bar"] == "1d"
    assert body["as_of"] == "2026-10-21T16:00:00Z"
    assert body["breadth"] == {
        "advancers": 8,
        "decliners": 2,
        "unchanged": 0,
        "ratio": "4",
        "participants": 10,
    }
    assert body["resonance"] == {"strength": "0.6", "participants": 10, "window": 20}


def test_endpoint_requires_the_class(client: TestClient) -> None:
    """横截面按类别分开统计：`inst_type` 必填，缺了就 422。"""

    assert client.get("/api/market/breadth").status_code == 422
    assert client.get("/api/market/breadth", params={"inst_type": "SPOT"}).status_code == 200
