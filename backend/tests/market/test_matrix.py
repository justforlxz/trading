"""相关矩阵与快照：3×3 手算、缺样本、`as_of` 边界与按产品键回看。

手算用例：四个等间隔样本，三组收盘价按中心化向量直接算 Pearson：

- A = 10, 12, 14, 16（中心化 -3, -1, 1, 3，平方和 20）
- B = 101, 103, 99, 97（中心化 1, 3, -1, -3，平方和 20）
- C = 52, 48, 52, 48（中心化 2, -2, 2, -2，平方和 16）

于是 A-B = (-3-3-1-9)/20 = -0.8，A-C = (-6+2+2-6)/√320 = -8/√320，
B-C = (2-6-2+6)/√320 = 0.0，对角线为 1.0。

每个用例一个临时 schema（根 conftest 负责），表结构由 Alembic 迁移建出。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core import Bar, Timeframe, ValidationError
from app.db import session_scope
from app.instrument import sync_instruments
from app.market import (
    CorrelationSnapshot,
    correlation_matrix,
    load_snapshot,
    save_snapshot,
    upsert_candles,
)
from tests.factories.instruments import make_ref, make_swap_ref

SYMBOL_A = "XAAPL-USDT"
SYMBOL_B = "XMSFT-USDT"
SYMBOL_C = "XTSLA-USDT"
SYMBOL_SHORT = "XSHORT-USDT"

START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
TOL = 1e-9


def _moment(hours: int) -> datetime:
    return START + timedelta(hours=hours)


def _write(
    symbol: str,
    closes: list[float],
    *,
    offset: timedelta = timedelta(),
    source: str = "okx_spot",
) -> None:
    """从 `START`（可整体平移）起每小时写一根 1h K 线。"""

    rows = []
    for index, close in enumerate(closes):
        price = Decimal(str(close))
        rows.append(
            Bar(
                inst_id=symbol,
                timeframe=Timeframe.parse("1h"),
                open_time=_moment(index) + offset,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=Decimal("1"),
                confirm=True,
                source=source,
            )
        )
    upsert_candles(rows)


def _write_three() -> None:
    _write(SYMBOL_A, [10.0, 12.0, 14.0, 16.0])
    _write(SYMBOL_B, [101.0, 103.0, 99.0, 97.0])
    _write(SYMBOL_C, [52.0, 48.0, 52.0, 48.0])


def _register(*symbols: str) -> None:
    """把标的登记进 `instruments`：快照按产品键存储，必须先有产品键。"""

    refs = [
        # 代币化股票现货的 `baseCcy` 带 `X` 标记，产品键由 instrument 域去掉它。
        make_ref(inst_id=symbol, base_ccy=symbol.removesuffix("-USDT"))
        for symbol in symbols
    ]
    sync_instruments(refs)


def _snapshot_rows() -> int:
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(CorrelationSnapshot)) or 0


# ---------------------------------------------------------------- 矩阵：3×3 手算


def test_three_by_three_hand_computed_cells() -> None:
    """九格逐个断言：对称、对角线为 1.0、三个交叉系数与手算一致。"""

    _write_three()

    matrix = correlation_matrix([SYMBOL_A, SYMBOL_B, SYMBOL_C], "1h", 4, _moment(3))

    assert matrix.symbols == (SYMBOL_A, SYMBOL_B, SYMBOL_C)
    assert matrix.bar == "1h"
    assert matrix.window == 4
    assert matrix.as_of == _moment(3)

    assert matrix[SYMBOL_A][SYMBOL_A] == 1.0
    assert matrix[SYMBOL_B][SYMBOL_B] == 1.0
    assert matrix[SYMBOL_C][SYMBOL_C] == 1.0

    assert matrix[SYMBOL_A][SYMBOL_B] == pytest.approx(-0.8, abs=TOL)
    assert matrix[SYMBOL_A][SYMBOL_C] == pytest.approx(-8.0 / (320.0**0.5), abs=TOL)
    assert matrix[SYMBOL_B][SYMBOL_C] == pytest.approx(0.0, abs=TOL)

    for left in matrix.symbols:
        for right in matrix.symbols:
            assert matrix[left][right] == matrix[right][left]
            assert matrix.sample_size(left, right) == 4


def test_as_of_is_inclusive_and_excludes_later_bars() -> None:
    """`as_of` 落在某根 K 线上时那根算进来，之后的 K 线不算。"""

    _write_three()

    matrix = correlation_matrix([SYMBOL_A, SYMBOL_B], "1h", 4, _moment(2))

    assert matrix.sample_size(SYMBOL_A, SYMBOL_B) == 3
    # 手算前三条：A = 10, 12, 14 与 B = 101, 103, 99 都是中心化后方差 8 的对称序列，
    # 协方差 = 0*0 + 0*2 + 2*(-2) = -4，系数 = -4 / 8 = -0.5。
    assert matrix[SYMBOL_A][SYMBOL_B] == pytest.approx(-0.5, abs=TOL)


def test_short_symbol_has_undefined_cells_with_truthful_samples() -> None:
    """样本不足的标的：交叉格与对角线都是 `None`，`samples` 写实际条数。"""

    _write_three()
    _write(SYMBOL_SHORT, [5.0, 6.0])

    matrix = correlation_matrix([SYMBOL_A, SYMBOL_SHORT], "1h", 4, _moment(3))

    assert matrix[SYMBOL_SHORT][SYMBOL_SHORT] is None
    assert matrix[SYMBOL_A][SYMBOL_SHORT] is None
    assert matrix.sample_size(SYMBOL_SHORT, SYMBOL_A) == 2


def test_unaligned_timestamps_leave_the_cell_empty() -> None:
    """`open_time` 完全对不上时交集为空：系数 `None`、样本 0，不插值也不平移。"""

    _write_three()
    _write(SYMBOL_SHORT, [5.0, 6.0, 7.0], offset=timedelta(minutes=30))

    matrix = correlation_matrix([SYMBOL_A, SYMBOL_SHORT], "1h", 3, _moment(3))

    assert matrix[SYMBOL_A][SYMBOL_SHORT] is None
    assert matrix.sample_size(SYMBOL_A, SYMBOL_SHORT) == 0


def test_matrix_rejects_bad_arguments() -> None:
    with pytest.raises(ValidationError):
        correlation_matrix([], "1h", 4, _moment(0))
    with pytest.raises(ValidationError):
        correlation_matrix([SYMBOL_A, SYMBOL_A], "1h", 4, _moment(0))
    with pytest.raises(ValidationError):
        correlation_matrix([SYMBOL_A], "1h", 0, _moment(0))
    with pytest.raises(ValidationError):
        correlation_matrix([SYMBOL_A], "1h", 4, datetime(2026, 11, 6, 0, 0))
    with pytest.raises(ValidationError):
        correlation_matrix([SYMBOL_A], "7m", 4, _moment(0))


def test_multi_source_symbol_requires_an_explicit_source() -> None:
    """同一标的混存两种来源时不猜：不指定来源直接报错。"""

    _write(SYMBOL_A, [10.0, 12.0, 14.0, 16.0], source="okx_swap")
    _write(SYMBOL_A, [1.0, 2.0, 3.0, 4.0], source="us_equity_proxy")
    _write(SYMBOL_B, [101.0, 103.0, 99.0, 97.0], source="okx_swap")

    with pytest.raises(ValidationError):
        correlation_matrix([SYMBOL_A, SYMBOL_B], "1h", 4, _moment(3))


def test_source_filter_keeps_one_series_per_symbol() -> None:
    """指定来源后只用该来源的 K 线：系数等于该来源的读数，另一来源的行不参与。"""

    _write(SYMBOL_A, [10.0, 12.0, 14.0, 16.0], source="okx_swap")
    _write(SYMBOL_A, [1.0, 2.0, 3.0, 4.0], source="us_equity_proxy")
    _write(SYMBOL_B, [101.0, 103.0, 99.0, 97.0], source="okx_swap")

    matrix = correlation_matrix([SYMBOL_A, SYMBOL_B], "1h", 4, _moment(3), source="okx_swap")

    assert matrix[SYMBOL_A][SYMBOL_A] == 1.0
    assert matrix[SYMBOL_A][SYMBOL_B] == pytest.approx(-0.8, abs=TOL)
    assert matrix.sample_size(SYMBOL_A, SYMBOL_B) == 4

    # 换成代理行情来源：B 没有这个来源的行，交集为空，系数与样本都归零。
    other = correlation_matrix([SYMBOL_A, SYMBOL_B], "1h", 4, _moment(3), source="us_equity_proxy")
    assert other[SYMBOL_A][SYMBOL_B] is None
    assert other.sample_size(SYMBOL_A, SYMBOL_B) == 0


# ---------------------------------------------------------------- 快照：写入与回看


def test_saving_the_same_as_of_twice_adds_no_row() -> None:
    """同一 `as_of` 重复保存只覆盖：行数不变，数值不变。"""

    _write_three()
    _register(SYMBOL_A, SYMBOL_B, SYMBOL_C)
    matrix = correlation_matrix([SYMBOL_A, SYMBOL_B, SYMBOL_C], "1h", 4, _moment(3))

    first = save_snapshot(matrix)
    second = save_snapshot(matrix)

    # 3 个产品：对角线 3 格 + 交叉 3 格。
    assert first == 6
    assert second == 6
    assert _snapshot_rows() == 6


def test_snapshot_reads_back_the_same_matrix_by_product_key() -> None:
    """回看得到同一张矩阵：标识换成产品键，系数与样本数逐个一致。"""

    _write_three()
    _register(SYMBOL_A, SYMBOL_B, SYMBOL_C)
    matrix = correlation_matrix([SYMBOL_A, SYMBOL_B, SYMBOL_C], "1h", 4, _moment(3))
    save_snapshot(matrix)

    loaded = load_snapshot(as_of=_moment(3), bar="1h", window=4)

    assert loaded is not None
    assert loaded.symbols == ("AAPL", "MSFT", "TSLA")
    assert loaded["AAPL"]["AAPL"] == 1.0
    assert loaded["AAPL"]["MSFT"] == pytest.approx(-0.8, abs=TOL)
    assert loaded["AAPL"]["TSLA"] == pytest.approx(-8.0 / (320.0**0.5), abs=TOL)
    assert loaded["MSFT"]["TSLA"] == pytest.approx(0.0, abs=TOL)
    assert loaded["MSFT"]["TSLA"] == loaded["TSLA"]["MSFT"]
    assert loaded.sample_size("AAPL", "TSLA") == 4
    assert loaded.bar == "1h"
    assert loaded.window == 4
    assert loaded.as_of == _moment(3)


def test_load_snapshot_rejects_non_positive_window() -> None:
    with pytest.raises(ValidationError):
        load_snapshot(as_of=_moment(3), bar="1h", window=0)


def test_loading_an_unsaved_moment_returns_none() -> None:
    _write_three()
    _register(SYMBOL_A, SYMBOL_B)
    save_snapshot(correlation_matrix([SYMBOL_A, SYMBOL_B], "1h", 4, _moment(3)))

    assert load_snapshot(as_of=_moment(2), bar="1h", window=4) is None
    assert load_snapshot(as_of=_moment(3), bar="4h", window=4) is None
    assert load_snapshot(as_of=_moment(3), bar="1h", window=60) is None


def test_snapshot_requires_a_registered_product_key() -> None:
    """标的没登记就没有产品键：直接报错，不拿交易所标识顶替。"""

    _write_three()
    _register(SYMBOL_A, SYMBOL_B)
    matrix = correlation_matrix([SYMBOL_A, SYMBOL_C], "1h", 4, _moment(3))

    with pytest.raises(ValidationError):
        save_snapshot(matrix)
    assert _snapshot_rows() == 0


def test_snapshot_rejects_two_forms_of_the_same_product() -> None:
    """同一产品的现货与永续不能同时进一张矩阵：它们会折成同一个产品键。"""

    _write(SYMBOL_A, [10.0, 12.0, 14.0, 16.0])
    _write("AAPL-USDT-SWAP", [10.0, 12.0, 14.0, 16.0])
    _register(SYMBOL_A)
    sync_instruments([make_swap_ref()])
    matrix = correlation_matrix([SYMBOL_A, "AAPL-USDT-SWAP"], "1h", 4, _moment(3))

    with pytest.raises(ValidationError):
        save_snapshot(matrix)
