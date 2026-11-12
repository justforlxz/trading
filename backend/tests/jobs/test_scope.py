"""标的集合解析：五种模式各自读真源，顺序固定，空集合与非手选输入判错。

库里只写本用例需要的几行标的与两根日线（加自选要先算得出行情），因此每个模式的
结果都能逐条对上，不依赖任何外部数据。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, Timeframe, ValidationError
from app.instrument import sync_instruments
from app.jobs import SCOPE_MODES, TargetScope, resolve_scope
from app.market import upsert_candles
from app.watchlist import add_item
from tests.factories.instruments import make_ref, make_swap_ref

DAY = timedelta(days=1)
START = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)

APPLE_SPOT = "XAAPL-USDT"
MSFT_SPOT = "XMSFT-USDT"
APPLE_SWAP = "AAPL-USDT-SWAP"
SUSPENDED_SPOT = "XTSLA-USDT"

pytestmark = pytest.mark.usefixtures("job_schema")


def test_scope_modes_match_the_api_contract() -> None:
    """五种模式与 `api.schemas.backtest.BacktestTargets.mode` 的取值一一对应。"""

    assert SCOPE_MODES == ("single", "list", "watchlist", "group", "all")


def _seed_instruments() -> None:
    """四行标的：两条现货、一条看懂永续、一条停牌现货。"""

    sync_instruments(
        [
            make_ref(inst_id=APPLE_SPOT, base_ccy="XAAPL"),
            make_ref(inst_id=MSFT_SPOT, base_ccy="XMSFT"),
            make_swap_ref(inst_id=APPLE_SWAP),
            make_ref(inst_id=SUSPENDED_SPOT, base_ccy="XTSLA", state="suspend"),
        ]
    )


def _daily(inst_id: str) -> None:
    """写入两根日线：加自选要先算得出 24 小时涨跌幅。"""

    upsert_candles(
        [
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse("1d"),
                open_time=START + DAY * index,
                open=Decimal("100") + index,
                high=Decimal("100") + index,
                low=Decimal("100") + index,
                close=Decimal("100") + index,
                volume=Decimal("10"),
                confirm=True,
                source="okx",
            )
            for index in range(2)
        ]
    )


def _add(inst_id: str, group: str) -> None:
    _daily(inst_id)
    add_item(inst_id, group)


def test_single_scope_returns_the_one_symbol() -> None:
    _seed_instruments()

    assert resolve_scope(TargetScope(mode="single", inst_ids=(APPLE_SPOT,))) == (APPLE_SPOT,)


def test_list_scope_deduplicates_and_keeps_the_input_order() -> None:
    _seed_instruments()

    resolved = resolve_scope(TargetScope(mode="list", inst_ids=(MSFT_SPOT, APPLE_SPOT, MSFT_SPOT)))

    assert resolved == (MSFT_SPOT, APPLE_SPOT)


def test_list_scope_trims_whitespace_around_symbols() -> None:
    _seed_instruments()

    assert resolve_scope(TargetScope(mode="list", inst_ids=(" XAAPL-USDT ",))) == (APPLE_SPOT,)


def test_single_scope_rejects_a_symbol_missing_from_the_catalogue() -> None:
    _seed_instruments()

    with pytest.raises(ValidationError, match="标的 XNOPE-USDT 不在标的清单里"):
        resolve_scope(TargetScope(mode="single", inst_ids=("XNOPE-USDT",)))


def test_watchlist_scope_returns_every_tracked_symbol_in_symbol_order() -> None:
    _seed_instruments()
    _add(MSFT_SPOT, "科技")
    _add(APPLE_SPOT, "默认")

    assert resolve_scope(TargetScope(mode="watchlist")) == (APPLE_SPOT, MSFT_SPOT)


def test_group_scope_returns_only_that_group() -> None:
    _seed_instruments()
    _add(MSFT_SPOT, "科技")
    _add(APPLE_SPOT, "默认")

    assert resolve_scope(TargetScope(mode="group", group="科技")) == (MSFT_SPOT,)


def test_group_scope_rejects_a_group_without_symbols() -> None:
    _seed_instruments()
    _add(APPLE_SPOT, "默认")

    with pytest.raises(ValidationError, match="自选分组 科技 里没有可回测的标的"):
        resolve_scope(TargetScope(mode="group", group="科技"))


def test_watchlist_scope_rejects_an_empty_watchlist() -> None:
    _seed_instruments()

    with pytest.raises(ValidationError, match="自选里没有可回测的标的"):
        resolve_scope(TargetScope(mode="watchlist"))


def test_all_scope_returns_both_forms_and_skips_suspended_symbols() -> None:
    _seed_instruments()

    resolved = resolve_scope(TargetScope(mode="all"))

    assert resolved == (APPLE_SWAP, APPLE_SPOT, MSFT_SPOT)
    assert SUSPENDED_SPOT not in resolved


def test_all_scope_rejects_an_empty_catalogue() -> None:
    with pytest.raises(ValidationError, match="没有可交易的标的"):
        resolve_scope(TargetScope(mode="all"))


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"mode": "single", "inst_ids": (APPLE_SPOT, MSFT_SPOT)}, "single 模式必须给 1 个标的"),
        ({"mode": "list"}, "list 模式至少要给 1 个标的"),
        ({"mode": "watchlist", "inst_ids": (APPLE_SPOT,)}, "watchlist 模式不接受手选标的"),
        ({"mode": "group"}, "group 模式必须给分组名"),
        (
            {"mode": "group", "group": "科技", "inst_ids": (APPLE_SPOT,)},
            "group 模式不接受",
        ),
        ({"mode": "single", "inst_ids": (APPLE_SPOT,), "group": "科技"}, "不接受分组名"),
        ({"mode": "all", "group": "科技"}, "all 模式不接受"),
        ({"mode": "unknown"}, "未知标的集合模式"),
        ({"mode": "list", "inst_ids": ("  ",)}, "标的集合里有空标识"),
    ],
)
def test_target_scope_rejects_mixed_or_incomplete_inputs(
    arguments: dict[str, object], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        TargetScope(**arguments)  # type: ignore[arg-type]


def test_resolve_scope_rejects_a_plain_string() -> None:
    with pytest.raises(ValidationError, match="必须是 TargetScope"):
        resolve_scope("single")  # type: ignore[arg-type]
