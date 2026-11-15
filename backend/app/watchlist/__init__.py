"""自选域门面：分组、条目与相关标的。

本包只对外发布服务函数与只读视图；持久化模型只发布一个名字，供装配根在建表
前把 `watchlists` / `watchlist_items` 拉进元数据。
"""

from app.watchlist.model import WatchlistItemRow
from app.watchlist.service import (
    RelatedCandidate,
    WatchlistEntry,
    WatchlistSummary,
    add_item,
    group_of,
    list_entries,
    list_groups,
    move_item,
    related_instruments,
    remove_item,
    summarize_entries,
    tracked_instruments,
)

__all__ = [
    "RelatedCandidate",
    "WatchlistEntry",
    "WatchlistItemRow",
    "WatchlistSummary",
    "add_item",
    "group_of",
    "list_entries",
    "list_groups",
    "move_item",
    "related_instruments",
    "remove_item",
    "summarize_entries",
    "tracked_instruments",
]
