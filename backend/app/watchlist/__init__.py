"""自选域门面：分组、条目与相关标的。

本包只对外发布服务函数与只读视图；持久化模型只发布一个名字，供装配根在建表
前把 `watchlists` / `watchlist_items` 拉进元数据。`WatchRegistry` 是常驻订阅集合：
关注列表标的与浏览器订阅的并集，推送层据此决定上游订什么。
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
from app.watchlist.watch_registry import WatchRegistry, watch_registry

__all__ = [
    "RelatedCandidate",
    "WatchRegistry",
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
    "watch_registry",
]
