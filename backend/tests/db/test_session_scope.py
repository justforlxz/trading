"""`session_scope` 的事务语义：正常提交、异常回滚、出作用域后仍可读属性。

用例直接写一行的标的（字段最少且都有明确含义），把注意力放在事务边界上。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import init_db, session_scope
from app.instrument import Instrument

SYMBOL = "XAAPL-USDT"


def _instrument() -> Instrument:
    """一行现货标的：只填非空列，精度与上市时间都留空。"""

    return Instrument(
        symbol=SYMBOL,
        inst_type="SPOT",
        product_key="AAPL",
        asset_type="tokenized_equity",
        exchange="okx",
        base_currency="AAPL",
        quote_currency="USDT",
        trading_status="live",
    )


def _symbols() -> list[str]:
    with session_scope() as session:
        return list(session.execute(select(Instrument.symbol)).scalars())


def test_session_scope_commits_on_success() -> None:
    init_db()

    with session_scope() as session:
        session.add(_instrument())

    assert _symbols() == [SYMBOL]


def test_session_scope_rolls_back_on_error() -> None:
    init_db()

    with pytest.raises(RuntimeError, match="boom"), session_scope() as session:
        session.add(_instrument())
        session.flush()  # 先真的发出 INSERT，回滚才有东西可撤。
        raise RuntimeError("boom")

    assert _symbols() == []


def test_committed_object_stays_readable_after_the_scope() -> None:
    init_db()

    with session_scope() as session:
        instrument = _instrument()
        session.add(instrument)

    assert instrument.symbol == SYMBOL
