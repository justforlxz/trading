"""instrument 域：分类来自上游字段、配对键、幂等同步与双形态查询。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core import ValidationError
from app.db import init_db, session_scope
from app.exchange.okx.instruments import parse_instruments
from app.instrument import (
    Instrument,
    InstrumentPair,
    get_instrument_pair,
    list_instruments,
    sync_instruments,
)
from tests.factories.instruments import SAMPLE_LIST_TIME, load_instruments, make_ref, make_swap_ref


@pytest.fixture(autouse=True)
def _schema() -> None:
    """每个用例都在临时库里建表（Instrument 已随导入注册到 metadata）。"""

    init_db()


def _by_symbol() -> dict[str, Instrument]:
    return {row.symbol: row for row in list_instruments()}


def test_asset_type_comes_from_inst_category() -> None:
    sync_instruments(
        [
            make_ref(),
            make_ref(inst_id="XRP-USDT", base_ccy="XRP", inst_category="1"),
            make_ref(inst_id="XAUT-USDT", base_ccy="XAUT", inst_category="4"),
        ]
    )

    rows = _by_symbol()

    assert rows["XAAPL-USDT"].asset_type == "tokenized_equity"
    assert rows["XRP-USDT"].asset_type == "crypto"
    assert rows["XAUT-USDT"].asset_type == "commodity_token"
    # 加密资产的 X 开头是币种本身的一部分，不能被当成代币化股票的标记剥掉。
    assert rows["XRP-USDT"].product_key == "XRP"
    assert rows["XAUT-USDT"].product_key == "XAUT"


def test_fake_ticker_with_crypto_category_is_not_prefix_stripped() -> None:
    sync_instruments([make_ref(inst_id="XFAKE-USDT", base_ccy="XFAKE", inst_category="1")])

    row = _by_symbol()["XFAKE-USDT"]

    assert row.asset_type == "crypto"
    assert row.product_key == "XFAKE"
    assert row.base_currency == "XFAKE"


def test_missing_category_is_unknown() -> None:
    sync_instruments([make_ref(inst_category="")])

    assert _by_symbol()["XAAPL-USDT"].asset_type == "unknown"


def test_tokenized_spot_drops_the_x_marker_for_pairing() -> None:
    sync_instruments([make_ref(), make_swap_ref()])

    spot, swap = _by_symbol()["XAAPL-USDT"], _by_symbol()["AAPL-USDT-SWAP"]

    assert spot.product_key == swap.product_key == "AAPL"
    assert spot.base_currency == swap.base_currency == "AAPL"
    assert spot.inst_type == "SPOT"
    assert swap.inst_type == "SWAP"


def test_sync_is_idempotent_and_updates_existing_rows() -> None:
    assert sync_instruments([make_ref(), make_swap_ref()]) == 2
    assert (
        sync_instruments([make_ref(state="suspend", tick_size=Decimal("0.02")), make_swap_ref()])
        == 2
    )

    rows = list_instruments()

    assert [row.symbol for row in rows] == ["AAPL-USDT-SWAP", "XAAPL-USDT"]
    assert rows[1].trading_status == "suspend"
    assert rows[1].tick_size == Decimal("0.02")


def test_live_instrument_has_data_start_at_listing_time() -> None:
    sync_instruments([make_ref()])

    row = _by_symbol()["XAAPL-USDT"]

    assert row.trading_status == "live"
    assert row.listing_time == SAMPLE_LIST_TIME
    assert row.data_start == SAMPLE_LIST_TIME


def test_preopen_instrument_keeps_unknown_precision_and_no_data_start() -> None:
    sync_instruments(
        [
            make_ref(
                state="preopen",
                tick_size=None,
                lot_size=None,
                min_size=None,
            )
        ]
    )

    row = _by_symbol()["XAAPL-USDT"]

    assert row.trading_status == "preopen"
    assert row.tick_size is None
    assert row.lot_size is None
    assert row.min_order_size is None
    assert row.listing_time == SAMPLE_LIST_TIME
    assert row.data_start is None


def test_swap_persists_contract_spec_and_currency() -> None:
    sync_instruments([make_ref(), make_swap_ref()])

    swap, spot = _by_symbol()["AAPL-USDT-SWAP"], _by_symbol()["XAAPL-USDT"]

    assert swap.quote_currency == "USDT"
    assert swap.settle_ccy == "USDT"
    assert swap.ct_val == Decimal("1")
    assert swap.ct_mult == Decimal("1")
    assert swap.ct_type == "linear"
    assert swap.max_lever == Decimal("20")
    # 现货没有合约参数，如实留空。
    assert spot.ct_val is None
    assert spot.ct_type is None
    assert spot.settle_ccy is None


def test_swap_without_ct_val_ccy_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ctValCcy"):
        sync_instruments([make_swap_ref(ct_val_ccy="")])

    assert list_instruments() == []


def test_swap_without_settle_ccy_is_rejected() -> None:
    with pytest.raises(ValidationError, match="settleCcy"):
        sync_instruments([make_swap_ref(settle_ccy="")])


def test_tokenized_spot_without_x_marker_is_rejected() -> None:
    with pytest.raises(ValidationError, match="X 标记"):
        sync_instruments([make_ref(base_ccy="AAPL")])


def test_spot_without_quote_currency_is_rejected() -> None:
    with pytest.raises(ValidationError, match="quoteCcy"):
        sync_instruments([make_ref(quote_ccy="")])


def test_crypto_spot_without_base_currency_is_rejected() -> None:
    with pytest.raises(ValidationError, match="baseCcy"):
        sync_instruments([make_ref(inst_category="1", base_ccy="")])


def test_unsupported_inst_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="instType"):
        sync_instruments([make_ref(inst_type="FUTURES")])


def test_missing_trading_state_is_rejected() -> None:
    with pytest.raises(ValidationError, match="state"):
        sync_instruments([make_ref(state="  ")])


def test_pair_returns_both_forms_of_one_product() -> None:
    sync_instruments([make_ref(), make_swap_ref()])

    pair = get_instrument_pair("AAPL")

    assert isinstance(pair, InstrumentPair)
    assert pair.product_key == "AAPL"
    assert pair.spot is not None and pair.spot.symbol == "XAAPL-USDT"
    assert pair.swap is not None and pair.swap.symbol == "AAPL-USDT-SWAP"


def test_pair_normalizes_whitespace_and_case() -> None:
    sync_instruments([make_ref()])

    assert get_instrument_pair(" aapl ").spot is not None


def test_pair_without_swap_returns_only_spot() -> None:
    sync_instruments([make_ref(inst_id="XRP-USDT", base_ccy="XRP", inst_category="1")])

    pair = get_instrument_pair("XRP")

    assert pair.spot is not None and pair.spot.symbol == "XRP-USDT"
    assert pair.swap is None


def test_pair_unknown_product_is_rejected() -> None:
    with pytest.raises(ValidationError, match="未找到产品"):
        get_instrument_pair("NOPE")


def test_pair_blank_product_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="产品键不能为空"):
        get_instrument_pair("   ")


def test_pair_prefers_the_spot_quote_matching_the_swap() -> None:
    sync_instruments(
        [
            make_ref(),
            make_ref(inst_id="XAAPL-USDC", quote_ccy="USDC"),
            make_swap_ref(),
        ]
    )

    pair = get_instrument_pair("AAPL")

    assert pair.spot is not None and pair.spot.quote_currency == "USDT"
    assert pair.spot.symbol == "XAAPL-USDT"


def test_pair_spot_only_falls_back_in_symbol_order() -> None:
    sync_instruments(
        [
            make_ref(inst_id="XAAPL-USDC", quote_ccy="USDC"),
            make_ref(inst_id="XAAPL-USDT"),
        ]
    )

    pair = get_instrument_pair("AAPL")

    assert pair.spot is not None and pair.spot.symbol == "XAAPL-USDT"


def test_pair_returns_single_quote_when_it_is_all_that_exists() -> None:
    sync_instruments([make_ref(inst_id="XAAPL-USDC", quote_ccy="USDC")])

    pair = get_instrument_pair("AAPL")

    assert pair.spot is not None and pair.spot.symbol == "XAAPL-USDC"


def test_crypto_tickers_starting_with_x_keep_their_own_product_key() -> None:
    sync_instruments(
        [
            make_ref(inst_id="XRP-USDT", base_ccy="XRP", inst_category="1"),
            make_ref(inst_id="XAU-USDT", base_ccy="XAU", inst_category="4"),
            make_ref(inst_id="XLM-USDT", base_ccy="XLM", inst_category="1"),
        ]
    )

    for product_key in ("XRP", "XAU", "XLM"):
        pair = get_instrument_pair(product_key)
        assert pair.spot is not None
        assert pair.spot.product_key == product_key
        assert pair.swap is None

    with session_scope() as session:
        stripped = list(
            session.scalars(
                select(Instrument.product_key).where(Instrument.product_key.in_(["RP", "AU", "LM"]))
            )
        )
    assert stripped == []


def test_sync_frozen_snapshot_matches_phase1_counts() -> None:
    refs = parse_instruments(load_instruments())

    assert sync_instruments(refs) == 429
    assert len(list_instruments()) == 429

    with session_scope() as session:
        with_key = session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.product_key.is_not(None))
        )
        spot_count = session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.inst_type == "SPOT")
        )
        swap_keys = select(Instrument.product_key).where(Instrument.inst_type == "SWAP")
        paired = session.scalar(
            select(func.count(func.distinct(Instrument.product_key)))
            .select_from(Instrument)
            .where(Instrument.inst_type == "SPOT", Instrument.product_key.in_(swap_keys))
        )

    assert (with_key, spot_count, paired) == (429, 199, 169)


@pytest.mark.parametrize(
    "product_key", ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD"]
)
def test_frozen_snapshot_pairs_known_products(product_key: str) -> None:
    sync_instruments(parse_instruments(load_instruments()))

    pair = get_instrument_pair(product_key)

    assert pair.spot is not None
    assert pair.swap is not None
    assert pair.spot.symbol == f"X{product_key}-USDT"
    assert pair.swap.symbol == f"{product_key}-USDT-SWAP"
