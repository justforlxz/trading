"""回测的标的集合：单标的 / 手动多选 / Watchlist 全部 / 自选分组 / 全部可交易。

解析一律走各域门面：标的清单的真源在 `instrument`，自选与分组的真源在 `watchlist`，
这里不自己拼 SQL，也不自己推字符串（`X` 前缀、`-USDT-SWAP` 后缀都不是本层该知道的）。

顺序是结果的一部分：手选与单标的模式保留用户给的顺序（只去掉重复），其余模式按
`symbol` 固定顺序。同一份库两次解析得到同一串标的，扫描结果才能和上一次逐行对齐。

空集合一律判错：自选空、分组空、库里没有可交易标的，都说明「这次没有可回测的」，
不返回空列表——空列表往下走会变成「跑完了，零条结果」，与「一个都没选中」分不开。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import ValidationError
from app.instrument import list_instruments, list_tradable
from app.watchlist import tracked_instruments

__all__ = ["SCOPE_MODES", "TargetScope", "resolve_scope"]

#: 五种标的集合模式，与 `api.schemas.backtest.BacktestTargets.mode` 一一对应。
SCOPE_MODES: tuple[str, ...] = ("single", "list", "watchlist", "group", "all")


@dataclass(frozen=True, slots=True)
class TargetScope:
    """一次批量回测要跑哪些标的：模式 + 手选清单（或分组名）。

    每个模式只接受自己的那一份入参，混着给直接判错：`watchlist` 模式又带 `inst_ids`
    时，调用方显然以为自己选的是另外几项，静默忽略哪一半都会给出他没要的结果。
    """

    mode: str
    inst_ids: tuple[str, ...] = ()
    group: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in SCOPE_MODES:
            raise ValidationError(f"未知标的集合模式 {self.mode!r}; 可选 {list(SCOPE_MODES)}")
        for inst_id in self.inst_ids:
            if not isinstance(inst_id, str) or not inst_id.strip():
                raise ValidationError(f"标的集合里有空标识: {inst_id!r}")
        if self.group is not None and (not isinstance(self.group, str) or not self.group.strip()):
            raise ValidationError("分组名不能为空")
        if self.mode in ("single", "list") and self.group is not None:
            raise ValidationError(f"{self.mode} 模式不接受分组名")
        if self.mode == "single" and len(self.inst_ids) != 1:
            raise ValidationError(f"single 模式必须给 1 个标的, 实际 {len(self.inst_ids)} 个")
        if self.mode == "list" and not self.inst_ids:
            raise ValidationError("list 模式至少要给 1 个标的")
        if self.mode in ("watchlist", "all") and self.inst_ids:
            raise ValidationError(f"{self.mode} 模式不接受手选标的")
        if self.mode in ("watchlist", "all") and self.group is not None:
            raise ValidationError(f"{self.mode} 模式不接受分组名")
        if self.mode == "group" and self.inst_ids:
            raise ValidationError("group 模式不接受手选标的")
        if self.mode == "group" and self.group is None:
            raise ValidationError("group 模式必须给分组名")


def resolve_scope(scope: TargetScope) -> tuple[str, ...]:
    """把标的集合模式解析成具体的交易所标识序列。

    手选与单标的模式会核对标的确实在库里：拼错一个标识时当场报错，而不是让每一格
    回测各自失败一遍。其余模式读真源清单，空集合判错并说清是哪一类空了。
    """

    if not isinstance(scope, TargetScope):
        raise ValidationError("标的集合必须是 TargetScope")

    if scope.mode in ("single", "list"):
        wanted = tuple(dict.fromkeys(inst_id.strip() for inst_id in scope.inst_ids))
        known = {row.symbol for row in list_instruments()}
        missing = [inst_id for inst_id in wanted if inst_id not in known]
        if missing:
            raise ValidationError(f"标的 {missing[0]} 不在标的清单里")
        return wanted

    if scope.mode == "watchlist":
        symbols = tuple(row.symbol for row in tracked_instruments())
        if not symbols:
            raise ValidationError("自选里没有可回测的标的")
        return symbols

    if scope.mode == "group":
        group = scope.group
        assert group is not None  # __post_init__ 已保证
        symbols = tuple(row.symbol for row in tracked_instruments(group))
        if not symbols:
            raise ValidationError(f"自选分组 {group} 里没有可回测的标的")
        return symbols

    symbols = tuple(row.symbol for row in list_tradable())
    if not symbols:
        raise ValidationError("标的清单里没有可交易的标的, 请先同步标的")
    return symbols
