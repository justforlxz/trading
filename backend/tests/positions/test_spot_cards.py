"""现货持仓的卡片：标记价从最近一根 K 线或公共 ticker 补、尘埃只在卡片列表里隐藏。

MKACG-1015 的现象是「15 张卡片只有 1 张有数据」：14 条现货余额的 `mark_px` 为空，
`notional` / `weight_pct` 全算不出来，界面只能显示骨架；其中大半还是名义价值不到
1 分钱的尘埃。功能检测又补了一条：K 线只覆盖自选/订阅，长尾持仓一个来源都没有，
于是 4 张卡永远「行情待同步」。本文件逐条钉住这些判据：

- 现货缺标记价时取该标的最近一根已收盘 K 线的收盘价（永续不拿收盘价冒充标记价）；
- 库里一个来源都没有时，现货兜底读一次 OKX 公共 ticker，取不到就留空；
- 标记价带来源与报价时刻，页面据此说明价格有多旧；
- 尘埃只在卡片列表里隐藏，快照行不删；隐藏条数经 `hidden_dust_count` 给出；
- 现货没有止损概念（`stop_supported=False`），不能显示成「未取到」；
- 现货的盈亏只在成本价已知时才算，上游的 0 不能读成「不亏不赚」；
- 占比分母取可见部分，可见卡片的 `weight_pct` 合计仍是 100%。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core import AccountSnapshot, ExchangePosition
from app.exchange import OkxClient
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from app.positions import exchange_positions, position_cards, record_exchange_snapshot
from app.positions import service as positions_service
from tests.api.conftest import latest_opens, seed_daily
from tests.exchange.conftest import SPOT_INSTRUMENT, SWAP_INSTRUMENT

CAPTURED_AT = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
TICKER_AT = datetime(2026, 11, 26, 3, 0, tzinfo=UTC)
DAY = timedelta(days=1)
SPOT_INST_ID = "XAAPL-USDT"
SWAP_INST_ID = "AAPL-USDT-SWAP"


@pytest.fixture(autouse=True)
def instruments() -> None:
    """两条标的都写进标的表：现货与永续各自的类别决定不同的取价规则。"""

    sync_instruments(parse_instruments([SPOT_INSTRUMENT, SWAP_INSTRUMENT]))


@pytest.fixture(autouse=True)
def clean_settings_cache():
    """阈值与凭证都从进程配置读；用例改过的环境变量不能漏到下一个用例。"""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        currency="USDT",
        equity=Decimal("1000"),
        available_equity=Decimal("600"),
        cash_balance=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        used_margin=Decimal("0"),
        available_margin=Decimal("600"),
        margin_ratio=Decimal("0"),
    )


def _spot(
    pos_id: str = "XAAPL-USDT:long",
    *,
    size: str = "0.1478",
    avg_px: str = "0",
    upl: str | None = None,
) -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id=SPOT_INST_ID,
        pos_side="long",
        size=Decimal(size),
        avg_px=Decimal(avg_px),
        mark_px=None,
        upl=None if upl is None else Decimal(upl),
        upl_ratio=None,
        # 现货没有杠杆、没有强平价、没有保证金：与适配层推导出的行同一形状。
        lever=None,
        mgn_mode=None,
        liq_px=None,
        margin=None,
    )


def _swap(
    pos_id: str = "AAPL-USDT-SWAP:long",
    *,
    size: str = "2",
    mark_px: str | None = "231.42",
) -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id=SWAP_INST_ID,
        pos_side="long",
        size=Decimal(size),
        avg_px=Decimal("226.80"),
        mark_px=None if mark_px is None else Decimal(mark_px),
        upl=Decimal("10"),
        upl_ratio=Decimal("0.02"),
        lever=Decimal("3"),
        mgn_mode="isolated",
        liq_px=None,
        margin=Decimal("0"),
    )


def _write(positions: list[ExchangePosition]) -> None:
    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_rest",
        snapshot=_snapshot(),
        positions=positions,
        stops=[],
        stops_available=True,
    )


def _patch_ticker(
    monkeypatch: pytest.MonkeyPatch, quotes: dict[str, tuple[str, datetime]]
) -> list[str]:
    """把兜底报价换成录制式应答；返回实际被请求过的 instId（用来证明有没有打上游）。"""

    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inst_id = request.url.params["instId"]
        asked.append(inst_id)
        if inst_id not in quotes:
            return httpx.Response(200, json={"code": "0", "msg": "", "data": []})
        last, ts = quotes[inst_id]
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "instId": inst_id,
                        "last": last,
                        "open24h": last,
                        "ts": str(round(ts.timestamp() * 1000)),
                    }
                ],
            },
        )

    client = OkxClient(
        settings=Settings(okx_rest_base_url="https://okx.test", okx_http_max_retries=0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(positions_service, "OkxClient", lambda **_kwargs: client)
    return asked


def test_spot_card_takes_the_mark_price_from_the_latest_candle(client: TestClient) -> None:
    """AC1：现货缺标记价，用库里最近一根日线的收盘价补，名义价值随之算得出来。"""

    seed_daily(SPOT_INST_ID, ["340", "350", "352.99"])
    _write([_spot()])

    card = position_cards().items[0]

    assert card.mark_px == Decimal("352.99")
    assert card.notional == Decimal("0.1478") * Decimal("352.99")


def test_swap_mark_price_is_never_taken_from_a_candle(client: TestClient) -> None:
    """永续的标记价由交易所给；缺了就留空，不拿收盘价冒充强平价口径。"""

    seed_daily(SWAP_INST_ID, ["231.42"])
    _write([_swap(mark_px=None)])

    card = position_cards().items[0]

    assert card.mark_px is None
    # 名义价值只要求「有一个价格」，与账户卡的合计口径一致。
    assert card.notional == Decimal("2") * Decimal("231.42")


def test_spot_profit_is_derived_only_when_the_cost_is_known(client: TestClient) -> None:
    """AC1：有成本价时算 `(标记价 − 成本价) × 数量`；成本未知时留空，不当成 0。"""

    seed_daily(SPOT_INST_ID, ["352.99"])

    _write([_spot("XAAPL-USDT:long", size="2", avg_px="300")])
    priced = position_cards().items[0]
    assert priced.upl == (Decimal("352.99") - Decimal("300")) * 2
    assert priced.upl_ratio == priced.upl / (Decimal("300") * 2)

    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_rest",
        snapshot=_snapshot(),
        positions=[_spot("XAAPL-USDT:long", size="2", avg_px="0")],
        stops=[],
        stops_available=True,
    )
    unknown = position_cards().items[0]
    assert unknown.mark_px == Decimal("352.99")
    assert unknown.upl is None
    assert unknown.upl_ratio is None


def test_dust_is_hidden_from_the_cards_but_kept_in_the_snapshot(client: TestClient) -> None:
    """AC2：名义价值低于阈值的行不进列表，快照里一行都不删，隐藏条数如实给出。"""

    seed_daily(SPOT_INST_ID, ["352.99"])
    _write(
        [
            _spot("XAAPL-USDT:dust", size="0.000001"),
            _spot("XAAPL-USDT:long", size="0.1478"),
        ]
    )

    view = position_cards()

    assert [card.pos_id for card in view.items] == ["XAAPL-USDT:long"]
    assert view.hidden_dust_count == 1
    # 历史对账还要这些行：快照读侧照旧给出两条。
    assert len(exchange_positions().items) == 2


def test_a_row_without_any_quote_is_not_treated_as_dust(client: TestClient) -> None:
    """算不出名义价值的行照样出卡片：不能拿「没有价格」断言它「不到 1 USDT」。

    兜底报价被 conftest 关掉（单测不联网），因此这里就是「库里没有 K 线、上游也取不到」
    的最坏情形。
    """

    _write([_spot()])

    view = position_cards()

    assert [card.pos_id for card in view.items] == ["XAAPL-USDT:long"]
    assert view.items[0].notional is None
    assert view.hidden_dust_count == 0


def test_the_dust_threshold_comes_from_the_process_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阈值可配置：把它降到 0.1 USDT 后，名义 0.35 的持仓重新出现在列表里。"""

    seed_daily(SPOT_INST_ID, ["352.99"])
    _write([_spot(size="0.001")])
    assert position_cards().hidden_dust_count == 1

    monkeypatch.setenv("POSITION_DUST_NOTIONAL", "0.1")
    get_settings.cache_clear()

    assert position_cards().hidden_dust_count == 0


def test_spot_cards_have_no_stop_concept(client: TestClient) -> None:
    """AC3：现货不标「未取到」——它根本没有止损；永续照旧按三态给出。"""

    seed_daily(SPOT_INST_ID, ["352.99"])
    _write([_spot(), _swap()])

    cards = {card.pos_id: card for card in position_cards().items}

    assert cards["XAAPL-USDT:long"].stop_supported is False
    assert cards["AAPL-USDT-SWAP:long"].stop_supported is True


def test_spot_and_swap_of_one_product_carry_different_forms(client: TestClient) -> None:
    """AC6：同一产品名的两张卡片靠 `inst_type` 区分形态，不再看起来是同一个标的。"""

    seed_daily(SPOT_INST_ID, ["352.99"])
    _write([_spot(), _swap()])

    cards = {card.inst_id: card for card in position_cards().items}
    spot = cards[SPOT_INST_ID]
    swap = cards[SWAP_INST_ID]

    # 产品名按设计保持产品级：单标的敞口靠它把现货与永续合并（见 `risk/exposure.py`）。
    assert spot.display_symbol == swap.display_symbol == "AAPL-USDT"
    # 形态不同，界面据此标出「现货 / 永续」，两张卡片才能被分辨。
    assert (spot.inst_type, swap.inst_type) == ("SPOT", "SWAP")


def test_visible_weights_still_add_up_to_one_hundred(client: TestClient) -> None:
    """AC4：占比分母取可见部分，合计仍是 100%，且大小顺序与名义价值一致。"""

    seed_daily(SPOT_INST_ID, ["100"])
    _write(
        [
            _spot("XAAPL-USDT:long", size="1"),  # 名义 100
            _spot("XAAPL-USDT:dust", size="0.000001"),  # 尘埃，隐藏
            _swap("AAPL-USDT-SWAP:long", size="2"),  # 名义 462.84
        ]
    )

    view = position_cards()
    weights = [card.weight_pct for card in view.items]

    assert all(weight is not None for weight in weights)
    assert sum(weight for weight in weights if weight is not None) == pytest.approx(
        Decimal("100"), abs=Decimal("0.1")
    )
    assert view.hidden_dust_count == 1
    by_notional = sorted(view.items, key=lambda card: card.notional or Decimal(0), reverse=True)
    assert [card.pos_id for card in by_notional] == [
        card.pos_id
        for card in sorted(view.items, key=lambda card: card.weight_pct or Decimal(0), reverse=True)
    ]


def test_the_api_reports_the_hidden_dust_count(client: TestClient) -> None:
    """AC2 契约：接口给出 `hidden_dust_count`，卡片带 `stop_supported`。"""

    seed_daily(SPOT_INST_ID, ["352.99"])
    _write([_spot("XAAPL-USDT:dust", size="0.000001"), _spot()])

    response = client.get("/api/positions/cards")

    assert response.status_code == 200
    body = response.json()
    assert body["hidden_dust_count"] == 1
    assert body["items"][0]["stop_supported"] is False


def test_spot_without_candles_falls_back_to_the_public_ticker(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1 兜底：库里一行 K 线都没有的现货，用 OKX 公共 ticker 补上标记价。"""

    _write([_spot(size="0.6259")])
    _patch_ticker(monkeypatch, {"XAAPL-USDT": ("26.61", TICKER_AT)})

    card = position_cards().items[0]

    assert card.mark_px == Decimal("26.61")
    assert card.mark_px_source == "okx_ticker"
    assert card.mark_px_at == TICKER_AT
    assert card.notional == Decimal("0.6259") * Decimal("26.61")


def test_the_fallback_price_makes_dust_detection_work(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2：兜底价让「没有 K 线的尘埃」也能算出来，不必再以卡片形式占位。"""

    _write(
        [
            _spot("XAAPL-USDT:dust", size="0.000001"),
            _spot("XAAPL-USDT:long", size="0.6259"),
        ]
    )
    _patch_ticker(monkeypatch, {"XAAPL-USDT": ("26.61", TICKER_AT)})

    view = position_cards()

    assert [card.pos_id for card in view.items] == ["XAAPL-USDT:long"]
    assert view.hidden_dust_count == 1


def test_a_candle_price_wins_over_the_fallback_and_carries_its_own_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有 K 线就不打上游；标记价带上那根 K 线的来源与收盘时刻。"""

    seed_daily(SPOT_INST_ID, ["340", "352.99"])
    _write([_spot()])
    ticker_calls = _patch_ticker(monkeypatch, {"XAAPL-USDT": ("26.61", TICKER_AT)})

    card = position_cards().items[0]

    assert ticker_calls == []
    assert card.mark_px == Decimal("352.99")
    # 来源就是那根 K 线的来源，不是兜底的 `okx_ticker`。
    assert card.mark_px_source == "okx"
    # 收盘时刻 = 开盘时刻 + 一个日线周期。
    assert card.mark_px_at == latest_opens(2)[-1] + DAY


def test_the_fallback_is_skipped_when_upstream_is_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """兜底取不到价时卡片留空，不编价格、也不把整页请求拖失败。"""

    from app.exchange import ExchangeError

    def _boom(**_kwargs: object) -> None:
        raise ExchangeError("上游不可用")

    from app.positions import service as positions_service

    monkeypatch.setattr(positions_service, "OkxClient", _boom)
    _write([_spot()])

    view = position_cards()

    assert view.items[0].mark_px is None
    assert view.items[0].mark_px_source is None
    assert view.items[0].notional is None


def test_spot_profit_is_unknown_when_upstream_reports_zero(client: TestClient) -> None:
    """余额行上游把 `upl` 记 0（表示没有持仓成本），卡片不能显示成「不亏不赚」。"""

    seed_daily(SPOT_INST_ID, ["352.99"])
    _write([_spot(size="0.1478", avg_px="0", upl="0")])

    card = position_cards().items[0]

    assert card.mark_px == Decimal("352.99")
    assert card.upl is None
    assert card.upl_ratio is None
