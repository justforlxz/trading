"""自选域门面：分组、条目、价格提醒与相关标的。

本包只对外发布服务函数与只读视图；持久化模型只发布一个名字，供装配根在建表
前把 `watchlists` / `watchlist_items` / `price_alerts` 拉进元数据。
"""

from app.watchlist.model import WatchlistItemRow
from app.watchlist.service import (
    AlertSnapshot,
    RelatedCandidate,
    WatchlistEntry,
    add_item,
    clear_alert,
    list_entries,
    list_groups,
    move_item,
    related_instruments,
    remove_item,
    set_alert,
    tracked_instruments,
)

__all__ = [
    "AlertSnapshot",
    "RelatedCandidate",
    "WatchlistEntry",
    "WatchlistItemRow",
    "add_item",
    "clear_alert",
    "list_entries",
    "list_groups",
    "move_item",
    "related_instruments",
    "remove_item",
    "set_alert",
    "tracked_instruments",
]
