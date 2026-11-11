"""机会发现的服务编排：两种模式的端到端行为、可复现性与状态流转。

期望值都由「库里写了哪些标的与哪几根日线」反推：趋势来自窗口首尾收盘价，邻居来自
同一来源的相关系数，类别的方向来自涨跌家数。检测读到的来源必须是该标的在 `as_of`
那一刻的有效来源，因此夹具按同一条规则写库。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import DataUnavailable, ValidationError
from app.instrument import list_tradable
from app.opportunity import (
    LEG_LIMIT,
    MIN_ABS_CORRELATION,
    MODE_MARKET,
    MODE_TARGET,
    OpportunityRecord,
    detect_opportunities,
    get_opportunity,
    list_opportunities,
    set_status,
)
from tests.factories.instruments import make_ref
from tests.opportunity.conftest import (
    AS_OF,
    all_class_symbols,
    effective_source,
    seed_all_class_instruments,
    seed_daily,
    seed_instruments,
)

# 锚点自身没有方向（首尾收盘价都是 100），邻居与它同相位但收在高位。
ANCHOR_CLOSES = ["100", "120", "100", "120", "100"]
NEIGHBOUR_CLOSES = ["50", "60", "50", "60", "55"]

RISING_CLOSES = ["100", "105", "110", "115", "120", "125"]

# 本模块每个用例都要读写机会表：请求建表夹具，其余用例（纯函数）不请求。
pytestmark = pytest.mark.usefixtures("opportunity_schema")


def _seed_target_universe() -> None:
    """一个锚点（AAPL）与两个代币化股票邻居；三者都是现货，同一来源。"""

    seed_instruments(
        make_ref(),
        make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"),
        make_ref(inst_id="XNVDA-USDT", base_ccy="XNVDA"),
    )
    seed_daily("XAAPL-USDT", ANCHOR_CLOSES)
    seed_daily("XMSFT-USDT", NEIGHBOUR_CLOSES)
    seed_daily("XNVDA-USDT", NEIGHBOUR_CLOSES)


def test_target_mode_records_the_anchor_and_may_leave_it_out_of_the_legs() -> None:
    """AC：给定锚点 AAPL，机会的锚点是它；它自己没信号时腿里没有它。"""

    _seed_target_universe()

    records = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    assert len(records) == 1
    record = records[0]
    assert record.mode == MODE_TARGET
    assert record.anchor_product_key == "AAPL"
    assert record.status == "new"
    products = {leg.product_key for leg in record.legs}
    assert products == {"MSFT", "NVDA"}
    assert "AAPL" not in products
    # 趋势 10%：两条腿都是多头，强度就是趋势幅度。
    assert {leg.direction for leg in record.legs} == {"long"}
    assert {leg.score for leg in record.legs} == {Decimal("0.100000")}
    # 判定依据里的相关系数来自同一来源的两条序列，两条腿都过了 0.5 的门槛。
    assert record.evidence.startswith("{")
    assert MIN_ABS_CORRELATION == 0.5


def test_target_mode_keeps_the_anchor_as_a_leg_when_it_has_a_direction() -> None:
    """锚点自己有方向时它也是一条腿：锚点不被排除，只是不被特殊对待。"""

    seed_instruments(make_ref(), make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"))
    seed_daily("XAAPL-USDT", ["100", "105", "110"])
    seed_daily("XMSFT-USDT", ["50", "47", "45"])

    records = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    assert len(records) == 1
    directions = {leg.product_key: leg.direction for leg in records[0].legs}
    assert directions == {"AAPL": "long", "MSFT": "short"}


def test_target_mode_ignores_bars_stored_under_another_source() -> None:
    """邻居的 K 线存在另一个来源下时不算邻居：不同来源不能混成一条序列。"""

    seed_instruments(make_ref(), make_ref(inst_id="XETH-USDT", base_ccy="XETH"))
    seed_daily("XAAPL-USDT", ANCHOR_CLOSES)
    # XETH 是代币化股票现货，盘后读代理行情；这里只把它的日线写在 OKX 来源下。
    assert effective_source("XETH-USDT") != "okx_spot"
    seed_daily("XETH-USDT", NEIGHBOUR_CLOSES, source="okx_spot")

    assert detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL") == ()


def test_market_mode_scans_every_tradable_instrument_per_class() -> None:
    """AC：不传锚点时按类别扫描全部可交易标的，两类各自统计、不混。"""

    seed_all_class_instruments()
    spot_symbols = all_class_symbols("SPOT", 6)
    swap_symbols = all_class_symbols("SWAP", 6)
    for symbol in spot_symbols:
        seed_daily(symbol, RISING_CLOSES)
    for symbol in swap_symbols:
        seed_daily(symbol, RISING_CLOSES, inst_type="SWAP")

    records = detect_opportunities(AS_OF, "1d")

    assert {record.mode for record in records} == {MODE_MARKET}
    by_class = {record.legs[0].inst_type: record for record in records}
    assert set(by_class) == {"SPOT", "SWAP"}
    for inst_type, record in by_class.items():
        assert record.anchor_product_key is None
        # 腿只属本类别：两类标的的交易时段不同，混在一起统计没有意义。
        assert {leg.inst_type for leg in record.legs} == {inst_type}
        assert {leg.direction for leg in record.legs} == {"long"}
        # 条数不超过该类别的可交易标的数。
        assert len(record.legs) <= len(list_tradable(inst_type))
        assert len(record.legs) == LEG_LIMIT
    assert {leg.inst_id for leg in by_class["SPOT"].legs} <= set(spot_symbols)
    assert {leg.inst_id for leg in by_class["SWAP"].legs} <= set(swap_symbols)


def test_market_mode_returns_nothing_without_enough_participants() -> None:
    """样本太少时同向程度无从判断，不产出机会（也不拿一条腿凑一个）。"""

    seed_all_class_instruments()

    assert detect_opportunities(AS_OF, "1d") == ()


def test_detection_is_reproducible_for_the_same_as_of() -> None:
    """AC：同一 `as_of` 与同一输入重复执行，`opportunity_id` 集合完全相同。"""

    _seed_target_universe()

    first = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")
    second = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    assert {record.opportunity_id for record in first} == {
        record.opportunity_id for record in second
    }
    records, total = list_opportunities()
    assert total == len(first)
    assert len(records) == len(first)


def test_detection_does_not_overwrite_a_reviewed_status() -> None:
    """重跑检测不覆盖人工结论：状态是审核的结果，不是检测的输出。"""

    _seed_target_universe()
    (record,) = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")
    set_status(record.opportunity_id, "reviewed")

    (again,) = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    assert again.opportunity_id == record.opportunity_id
    assert again.status == "reviewed"
    assert again.legs == record.legs
    assert again.evidence == record.evidence


def test_list_filters_by_mode_anchor_and_status() -> None:
    """三个过滤条件各自生效，`total` 是过滤后的全部条数而不是本页条数。"""

    _seed_target_universe()
    seed_daily("XMSFT-USDT", ["50", "60", "50", "60", "70"])  # 邻居更强，换一个标识
    detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    by_mode, mode_total = list_opportunities(mode=MODE_TARGET)
    by_anchor, anchor_total = list_opportunities(anchor_product_key="aapl")
    by_status, status_total = list_opportunities(status="new")
    missing, missing_total = list_opportunities(status="adopted")
    limited, limited_total = list_opportunities(limit=1)

    assert mode_total == anchor_total == status_total == 1
    assert [record.opportunity_id for record in by_mode] == [
        record.opportunity_id for record in by_anchor
    ]
    assert len(by_status) == 1
    assert (missing, missing_total) == ((), 0)
    assert len(limited) == 1 and limited_total == 1


def test_list_rejects_unknown_filters() -> None:
    with pytest.raises(ValidationError):
        list_opportunities(mode="everything")
    with pytest.raises(ValidationError):
        list_opportunities(status="archived")
    with pytest.raises(ValidationError):
        list_opportunities(limit=0)


def test_set_status_walks_the_legal_path_and_rejects_the_rest() -> None:
    """服务层的状态流转与状态机同一条口径：非法转移直接抛，不静默忽略。"""

    _seed_target_universe()
    (record,) = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    reviewed = set_status(record.opportunity_id, "reviewed")
    assert reviewed is not None and reviewed.status == "reviewed"
    adopted = set_status(record.opportunity_id, "adopted")
    assert adopted is not None and adopted.status == "adopted"

    with pytest.raises(ValidationError):
        set_status(record.opportunity_id, "rejected")
    assert get_opportunity(record.opportunity_id).status == "adopted"


def test_set_status_and_get_return_none_for_an_unknown_opportunity() -> None:
    assert set_status("opp_missing", "reviewed") is None
    assert get_opportunity("opp_missing") is None


def test_detection_requires_candles_for_the_anchor() -> None:
    """锚点没有足够的 K 线时明确报缺数据，不用空候选冒充「没有机会」。"""

    seed_instruments(make_ref())
    seed_daily("XAAPL-USDT", ["100"])

    with pytest.raises(DataUnavailable):
        detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")


def test_detection_rejects_an_unaware_as_of() -> None:
    with pytest.raises(ValidationError):
        detect_opportunities(datetime(2026, 11, 10, 23, 0), "1d")


def test_records_carry_the_stored_legs_and_evidence() -> None:
    """落库再读回时，腿与判定依据原样还原（腿是记录，不是重算出来的）。"""

    _seed_target_universe()
    (detected,) = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")

    records, total = list_opportunities()
    assert total == 1
    (stored,) = records

    assert isinstance(stored, OpportunityRecord)
    assert stored.opportunity_id == detected.opportunity_id
    assert stored.as_of == AS_OF
    assert stored.score == detected.score
    assert stored.legs == detected.legs
    assert stored.evidence == detected.evidence
    assert stored.evidence.startswith("{") and "correlation" in stored.evidence
    assert stored.anchor_product_key == "AAPL"


def test_market_opportunities_carry_the_class_in_the_evidence() -> None:
    """市场驱动的机会没有锚点，类别写在判定依据里（表里没有类别列，也不需要）。"""

    seed_all_class_instruments()
    for symbol in all_class_symbols("SWAP", 5):
        seed_daily(symbol, RISING_CLOSES, inst_type="SWAP")

    records = detect_opportunities(AS_OF, "1d")

    assert len(records) == 1
    record = records[0]
    assert record.anchor_product_key is None
    assert '"inst_type":"SWAP"' in record.evidence


def test_detection_defaults_to_the_current_moment() -> None:
    """不给 `as_of` 时取当前时刻：库里没有当日行情时就是没有候选，不报错。"""

    seed_all_class_instruments()
    for symbol in all_class_symbols("SPOT", 5):
        seed_daily(symbol, RISING_CLOSES)

    records = detect_opportunities()

    assert all(isinstance(record, OpportunityRecord) for record in records)
    for record in records:
        assert record.as_of.tzinfo == UTC
        assert record.as_of.microsecond == 0
