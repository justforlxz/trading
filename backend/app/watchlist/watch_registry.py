"""常驻订阅集合：关注列表标的与浏览器订阅的并集。

上游行情订阅不能取决于有没有浏览器连着：关注列表里的标的在服务启动后一直订着，
浏览器订阅只是在它之上追加。本模块只回答「现在应该订阅哪些标的」，不自己发订阅、
不自己开连接，也不使用任何定时器——集合变了由调用方 `notify()` 通知，订阅方据此
重算一次。

关注列表只在启动与真正变化时读库（`refresh()`），读到的结果缓存在内存里：
`instruments()` 因此不会在事件循环里做数据库往返，也不会把数据库依赖带进推送层。
装配根（`app.main`）在启动时显式 `refresh()` 一次；没有初始化就直接读集合时只按空
集合处理并记一条警告，绝不回落到同步查库——那会把数据库依赖悄悄带回事件循环。
关注列表在 `add_item` / `remove_item` / `move_item` 提交后调用 `notify()`，所以新增
的标的立刻进入订阅集合，同时不需要等下一个浏览器连接。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

__all__ = ["WatchRegistry", "watch_registry"]

logger = logging.getLogger(__name__)

#: 浏览器订阅集合的来源，由推送层注入；没有浏览器连接时返回空集合。
BrowserSource = Callable[[], Iterable[str]]
#: 集合变化的订阅方；推送层在这里重算订阅，不使用定时器。
Listener = Callable[[], None]


def _tracked_symbols() -> list[str]:
    # 与本模块同包的服务模块在导入期会引用本模块的单例，因此这里延迟导入避免循环。
    from app.watchlist.service import tracked_instruments

    return [instrument.symbol for instrument in tracked_instruments()]


class WatchRegistry:
    """关注列表标的 ∪ 浏览器订阅集合，外加集合变化的通知。"""

    def __init__(self, *, tracked: Callable[[], Iterable[str]] | None = None) -> None:
        self._tracked = tracked or _tracked_symbols
        self._browser: BrowserSource | None = None
        self._listeners: list[Listener] = []
        self._resident: tuple[str, ...] | None = None
        self._warned = False
        if tracked is not None:
            # 注入来源的装配（测试与替身）在构造时读一次；生产单例由 main 启动时 refresh。
            self.refresh()

    def set_browser_source(self, source: BrowserSource | None) -> None:
        """注入浏览器订阅集合；注入前只看关注列表。"""

        self._browser = source

    def refresh(self) -> list[str]:
        """重读关注列表并刷新缓存；只有启动与关注列表变化时调用。"""

        self._resident = tuple(sorted({item.strip() for item in self._tracked() if item.strip()}))
        return list(self._resident)

    def instruments(self) -> list[str]:
        """当前应该订阅的标的：关注列表（内存缓存）∪ 浏览器订阅，按标识排序。

        缓存没初始化时只按空集合处理并警告一次——这里不读库，读库只在 `refresh()`。
        """

        if self._resident is None:
            if not self._warned:
                self._warned = True
                logger.warning("常驻订阅集合尚未初始化；先按空集合处理，装配根应调用 refresh()")
            self._resident = ()
        wanted = set(self._resident)
        if self._browser is not None:
            wanted.update(item.strip() for item in self._browser() if item and item.strip())
        return sorted(wanted)

    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify(self) -> None:
        """集合已变化：刷新缓存后通知每一位订阅方；一个订阅方失败不影响其他人。"""

        self.refresh()
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # 订阅方失败不能把已经提交的加入/移除自选变成 500
                logger.exception("常驻订阅集合的订阅方执行失败")


_WATCH_REGISTRY = WatchRegistry()


def watch_registry() -> WatchRegistry:
    """进程内唯一的常驻订阅集合；装配根向它注入浏览器订阅来源。"""

    return _WATCH_REGISTRY
