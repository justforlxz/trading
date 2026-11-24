"""大盘指数清单：整条大盘的判断只看这三个指数。

清单写在代码里而不是设置里：指数代码是上游（Yahoo）的固定代码，改名等于换标的；
用户不需要在这里做选择。它有两个使用方，共用同一份清单，不各写一张表：

- 美股渠道（`app.equity`）按它补齐**日线**：指数日线是 ATR 的唯一来源；
- 提醒扫描（`app.alerts`）按它产生「大盘异动」提醒。

指数不是可交易标的，不进 `instruments` 表（那里是 OKX 可交易品种与它们的交易规则）。
因此按这份清单产生的提醒 `instrument_id` 留空，指数代码与中文名写进提醒的载荷。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["INDEX_SYMBOLS", "MARKET_INDEXES", "MarketIndex"]


@dataclass(frozen=True, slots=True)
class MarketIndex:
    """一个用于大盘判断的指数：上游代码、中文名与稳定的规则标识前缀。"""

    symbol: str
    name: str
    #: 稳定标识：进规则标识与去重键，界面与日志里也用它区分三个指数。
    key: str


#: 纳指100、标普500、费城半导体。前两个代表大盘整体，费半代表高波动的板块风向。
MARKET_INDEXES: tuple[MarketIndex, ...] = (
    MarketIndex(symbol="^NDX", name="纳指100", key="ndx"),
    MarketIndex(symbol="^GSPC", name="标普500", key="gspc"),
    MarketIndex(symbol="^SOX", name="费城半导体", key="sox"),
)

#: 美股渠道要额外维护日线的指数代码。
INDEX_SYMBOLS: tuple[str, ...] = tuple(item.symbol for item in MARKET_INDEXES)
