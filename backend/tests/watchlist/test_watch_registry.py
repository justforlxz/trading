"""常驻订阅集合：关注列表 ∪ 浏览器订阅，且不依赖浏览器是否连着。

集合本身是纯逻辑（可注入来源直接断言）；与关注列表联动的那一半用真实数据库驱动，
断言 `add_item` / `remove_item` 提交后会通知订阅方重算。
"""

from __future__ import annotations

from app.instrument import sync_instruments
from app.watchlist import WatchRegistry, add_item, remove_item, watch_registry
from app.watchlist.watch_registry import logger as registry_logger
from tests.factories.instruments import make_ref, make_swap_ref


def test_instruments_is_the_union_of_watchlist_and_browser_subscriptions() -> None:
    registry = WatchRegistry(tracked=lambda: ["XAAPL-USDT", "AAPL-USDT-SWAP"])
    registry.set_browser_source(lambda: ["AAPL-USDT-SWAP", "BTC-USDT"])

    assert registry.instruments() == ["AAPL-USDT-SWAP", "BTC-USDT", "XAAPL-USDT"]


def test_ordered_instruments_puts_the_watchlist_first() -> None:
    """订阅超限时按这个顺序截断：关注列表（提醒规则按它跑）先占用名额。"""

    registry = WatchRegistry(tracked=lambda: ["XAAPL-USDT"])
    registry.set_browser_source(lambda: ["AAPL-USDT-SWAP", "BTC-USDT"])

    assert registry.ordered_instruments() == ["XAAPL-USDT", "AAPL-USDT-SWAP", "BTC-USDT"]
    assert registry.instruments() == ["AAPL-USDT-SWAP", "BTC-USDT", "XAAPL-USDT"]


def test_watchlist_instruments_stay_subscribed_without_any_browser() -> None:
    """AC1 的集合侧：没有浏览器来源时集合仍包含关注列表标的。"""

    registry = WatchRegistry(tracked=lambda: ["XAAPL-USDT"])

    assert registry.instruments() == ["XAAPL-USDT"]


def test_blank_entries_are_dropped() -> None:
    registry = WatchRegistry(tracked=lambda: ["XAAPL-USDT", "  "])

    assert registry.instruments() == ["XAAPL-USDT"]


def test_the_watchlist_is_read_once_and_cached_afterwards() -> None:
    """推送层每次订阅都调 `instruments()`，不能每次都查库。"""

    calls: list[int] = []

    def tracked() -> list[str]:
        calls.append(1)
        return ["XAAPL-USDT"]

    registry = WatchRegistry(tracked=tracked)

    assert registry.instruments() == ["XAAPL-USDT"]
    assert registry.instruments() == ["XAAPL-USDT"]
    assert len(calls) == 1

    registry.refresh()

    assert len(calls) == 2


def test_an_uninitialised_registry_treats_the_watchlist_as_empty(monkeypatch) -> None:
    """没有 refresh 过就只按空集合处理：推送层不能在这里悄悄查库。"""

    warned: list[str] = []
    monkeypatch.setattr(registry_logger, "warning", warned.append)
    registry = WatchRegistry()
    registry.set_browser_source(lambda: ["BTC-USDT"])

    assert registry.instruments() == ["BTC-USDT"]
    assert registry.instruments() == ["BTC-USDT"]

    assert len(warned) == 1


def test_a_failing_listener_does_not_break_the_others() -> None:
    """一个订阅方抛异常不能把已经提交的加入自选变成 500。"""

    registry = WatchRegistry(tracked=lambda: ["XAAPL-USDT"])
    seen: list[str] = []

    def broken() -> None:
        raise RuntimeError("订阅方坏了")

    registry.add_listener(broken)
    registry.add_listener(lambda: seen.append("ok"))

    registry.notify()

    assert seen == ["ok"]


def test_adding_a_watchlist_item_notifies_listeners_and_extends_the_set() -> None:
    sync_instruments([make_ref()])
    registry = watch_registry()
    calls: list[str] = []

    def listener() -> None:
        calls.append("notified")

    registry.add_listener(listener)
    try:
        add_item(make_ref().inst_id)
        # 关注列表来源真的读了库：新加入的标的立刻出现在常驻集合里。
        assert make_ref().inst_id in registry.instruments()
    finally:
        registry.remove_listener(listener)
        remove_item(make_ref().inst_id)

    assert calls


def test_removing_a_watchlist_item_notifies_listeners() -> None:
    sync_instruments([make_swap_ref()])
    registry = watch_registry()
    calls: list[str] = []

    def listener() -> None:
        calls.append("notified")

    add_item(make_swap_ref().inst_id)
    registry.add_listener(listener)
    try:
        remove_item(make_swap_ref().inst_id)
    finally:
        registry.remove_listener(listener)

    assert calls == ["notified"]
    assert make_swap_ref().inst_id not in registry.instruments()
