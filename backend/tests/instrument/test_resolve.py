"""标的解析与可交易集合：两种形态只经 `product_key` 关联，不做字符串推导。

两条被钉住的性质：

- `XAAPL-USDT` 与 `AAPL-USDT-SWAP` 互为对方形态，但关联只走 `product_key`；
  最近似的错误实现（去 `X` 前缀、拼 `-USDT-SWAP`）会在 `XRP` / `NO-SUCH` 上立刻
  暴露出来，因此这两条各有用例。
- 可交易集合按类别取、按 `state == live` 过滤，**不按资产类别过滤**：加密资产与
  代币化股票同属一个类别。期望条数从冻结快照现算，不写死数字。
"""

from __future__ import annotations

import pytest

from app.core import ValidationError
from app.db import init_db
from app.exchange.okx.instruments import parse_instruments
from app.instrument import list_tradable, resolve_instrument, sync_instruments
from tests.factories.instruments import load_instruments, make_ref, make_swap_ref

INST_TYPES = ("SPOT", "SWAP")


@pytest.fixture(autouse=True)
def _schema() -> None:
    """每个用例一个临时 schema，表结构走迁移（与生产同一条路径）。"""

    init_db()


@pytest.fixture
def aapl() -> None:
    """同一产品的两种形态：`XAAPL-USDT` 与 `AAPL-USDT-SWAP`，产品键 `AAPL`。"""

    sync_instruments([make_ref(), make_swap_ref()])


# ---------------------------------------------------------------- 解析：产品键与两种形态


def test_bare_product_key_returns_the_requested_form(aapl: None) -> None:
    assert resolve_instrument("AAPL", "SWAP").symbol == "AAPL-USDT-SWAP"
    assert resolve_instrument("AAPL", "SPOT").symbol == "XAAPL-USDT"


def test_either_symbol_crosses_to_the_other_form(aapl: None) -> None:
    """从现货标识取永续、从永续标识取现货：必须经 `product_key`，不能拼字符串。"""

    assert resolve_instrument("XAAPL-USDT", "SWAP").symbol == "AAPL-USDT-SWAP"
    assert resolve_instrument("AAPL-USDT-SWAP", "SPOT").symbol == "XAAPL-USDT"


@pytest.mark.parametrize(
    ("query", "inst_type", "expected"),
    [
        ("AAPL", "SWAP", "AAPL-USDT-SWAP"),
        ("aapl", "spot", "XAAPL-USDT"),
        ("  Aapl  ", "SWAP", "AAPL-USDT-SWAP"),
        ("xaapl-usdt", "SWAP", "AAPL-USDT-SWAP"),
        ("AAPL-USDT-SWAP", "SPOT", "XAAPL-USDT"),
    ],
)
def test_query_forms_are_normalized(query: str, inst_type: str, expected: str, aapl: None) -> None:
    assert resolve_instrument(query, inst_type).symbol == expected


def test_crypto_ticker_starting_with_x_keeps_its_own_code() -> None:
    """`XRP` 去掉 `X` 是不存在的 `RP-USDT`，解析必须原样返回。"""

    sync_instruments([make_ref(inst_id="XRP-USDT", base_ccy="XRP", inst_category="1")])

    assert resolve_instrument("XRP", "SPOT").symbol == "XRP-USDT"
    assert resolve_instrument("XRP-USDT", "SPOT").symbol == "XRP-USDT"


def test_spot_quote_matching_the_swap_wins() -> None:
    """同一产品挂两个现货报价时，取与永续同报价的那一档，结果不随后插入的行改变。"""

    sync_instruments(
        [make_ref(), make_ref(inst_id="XAAPL-USDC", quote_ccy="USDC"), make_swap_ref()]
    )

    assert resolve_instrument("AAPL", "SPOT").symbol == "XAAPL-USDT"


def test_unknown_query_is_rejected_instead_of_guessed(aapl: None) -> None:
    with pytest.raises(ValidationError, match="未找到标的"):
        resolve_instrument("NO-SUCH", "SPOT")


def test_unknown_query_does_not_fall_back_to_x_prefixed_symbol() -> None:
    """库里只有 `XAAPL-USDT` 时，`AAPL` 走产品键命中，而不是猜 `X` 前缀。"""

    sync_instruments([make_ref()])

    with pytest.raises(ValidationError, match="没有 SWAP 形态"):
        resolve_instrument("AAPL", "SWAP")


def test_blank_query_is_rejected(aapl: None) -> None:
    with pytest.raises(ValidationError, match="标的查询不能为空"):
        resolve_instrument("   ", "SPOT")


@pytest.mark.parametrize("inst_type", ["FUTURES", "   "])
def test_unsupported_category_is_rejected(inst_type: str, aapl: None) -> None:
    with pytest.raises(ValidationError, match="不在支持范围"):
        resolve_instrument("AAPL", inst_type)


def test_missing_form_is_rejected() -> None:
    sync_instruments([make_ref(inst_id="XRP-USDT", base_ccy="XRP", inst_category="1")])

    with pytest.raises(ValidationError, match="没有 SWAP 形态"):
        resolve_instrument("XRP", "SWAP")


# ------------------------------------------------------------ 可交易集合：类别与状态


def _snapshot_live_counts() -> dict[str, int]:
    """从冻结快照现算每类的可交易条数：夹具变了这里跟着变，不写死数字。"""

    rows = load_instruments()
    return {
        inst_type: sum(1 for row in rows if row["instType"] == inst_type and row["state"] == "live")
        for inst_type in INST_TYPES
    }


def test_counts_match_the_frozen_snapshot() -> None:
    sync_instruments(parse_instruments(load_instruments()))
    expected = _snapshot_live_counts()

    for inst_type in INST_TYPES:
        # 先确认期望值不是 0 或全量：否则「全部返回」与「一条不返回」都能让断言通过。
        assert 0 < expected[inst_type] < len(load_instruments())

        tradable = list_tradable(inst_type)
        assert len(tradable) == expected[inst_type]
        assert {row.inst_type for row in tradable} == {inst_type}
        assert {row.trading_status for row in tradable} == {"live"}


def test_non_live_rows_are_excluded() -> None:
    sync_instruments(
        [
            make_ref(),
            make_ref(inst_id="XTSLA-USDT", base_ccy="XTSLA", state="suspend"),
            make_ref(inst_id="XNVDA-USDT", base_ccy="XNVDA", state="preopen"),
        ]
    )

    assert [row.symbol for row in list_tradable("SPOT")] == ["XAAPL-USDT"]


def test_asset_categories_are_not_filtered() -> None:
    """加密资产、代币化股票、商品代币同属现货类别，全部返回。"""

    sync_instruments(
        [
            make_ref(),
            make_ref(inst_id="XRP-USDT", base_ccy="XRP", inst_category="1"),
            make_ref(inst_id="XAUT-USDT", base_ccy="XAUT", inst_category="4"),
        ]
    )

    rows = list_tradable("SPOT")

    assert [row.symbol for row in rows] == ["XAAPL-USDT", "XAUT-USDT", "XRP-USDT"]
    assert {row.asset_type for row in rows} == {
        "tokenized_equity",
        "commodity_token",
        "crypto",
    }


def test_order_is_stable_by_symbol() -> None:
    sync_instruments(
        [
            make_ref(inst_id="XTSLA-USDT", base_ccy="XTSLA"),
            make_ref(),
            make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"),
        ]
    )

    assert [row.symbol for row in list_tradable("SPOT")] == [
        "XAAPL-USDT",
        "XMSFT-USDT",
        "XTSLA-USDT",
    ]


@pytest.mark.parametrize("inst_type", ["swap", " Swap "])
def test_category_is_normalized(inst_type: str) -> None:
    sync_instruments([make_ref(), make_swap_ref()])

    assert [row.symbol for row in list_tradable(inst_type)] == ["AAPL-USDT-SWAP"]


@pytest.mark.parametrize("inst_type", ["FUTURES", "   "])
def test_tradable_rejects_unsupported_category(inst_type: str) -> None:
    """未注册的类别直接报错，不返回空列表假装「这一类没有标的」。"""

    with pytest.raises(ValidationError, match="不在支持范围"):
        list_tradable(inst_type)
