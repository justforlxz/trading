"""`session_scope` 的事务语义，以及可替换的会话来源。

前三支用例看的是**默认**工作单元（一次会话一条池连接）的提交、回滚与「出作用域后
仍可读属性」，所以整模块标 `dedicated_database`：默认工作单元真的提交到自己的库上，
不受测试装配的 savepoint 会话影响。

后两支看注入口本身：`set_session_scope_factory` 换掉的工厂必须被 `session_scope`
采纳，传 `None` 必须回到默认工作单元。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import init_db, session_scope, set_session_scope_factory
from app.db.engine import get_engine
from app.instrument import Instrument

pytestmark = pytest.mark.dedicated_database

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


def test_injected_factory_is_used_by_session_scope() -> None:
    """注入口生效：换掉工厂后，`session_scope` 给出工厂产出的会话。"""

    sentinel: object = object()
    calls: list[str] = []

    @contextmanager
    def _factory() -> Iterator[object]:
        calls.append("opened")
        yield sentinel

    set_session_scope_factory(_factory)  # type: ignore[arg-type]
    try:
        with session_scope() as session:
            assert session is sentinel
    finally:
        set_session_scope_factory(None)

    assert calls == ["opened"]


def test_restoring_the_default_factory_binds_sessions_to_the_engine() -> None:
    """传 `None` 恢复默认：会话重新绑在引擎上，而不是上一次换进去的工厂。"""

    @contextmanager
    def _factory() -> Iterator[None]:
        yield None

    set_session_scope_factory(_factory)  # type: ignore[arg-type]
    set_session_scope_factory(None)

    with session_scope() as session:
        assert isinstance(session, Session)
        assert session.get_bind() is get_engine()
