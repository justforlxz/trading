"""关系变化检测：把两次快照的边对比成「显著变化」列表（纯函数）。

判定口径：
- 新增 / 消失的边本身就是变化；
- 系数变化超过阈值（默认 0.2）为显著；
- 符号翻转无论幅度大小都单独标记（正相关转负相关是策略上的性质变化）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

KIND_ADDED = "added"
KIND_REMOVED = "removed"
KIND_CHANGED = "changed"


@dataclass(frozen=True, slots=True)
class RelationChange:
    """单条边的变化；`counterparty` 由调用方提供的键（inst_id）标识。"""

    counterparty: str
    kind: str
    previous: float | None
    current: float | None
    delta: float | None
    sign_flip: bool
    significant: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "counterparty": self.counterparty,
            "kind": self.kind,
            "previous": self.previous,
            "current": self.current,
            "delta": self.delta,
            "sign_flip": self.sign_flip,
            "significant": self.significant,
        }


def significant_changes(
    previous: Mapping[str, float],
    current: Mapping[str, float],
    *,
    threshold: float = 0.2,
) -> list[RelationChange]:
    """对比两次快照的 `{counterparty: coefficient}`，返回全部显著变化。

    结果按 |delta| 降序（新增/消失按 |current| / |previous| 参与排序），
    空字典返回空列表。
    """

    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    changes: list[RelationChange] = []
    for key in sorted(set(previous) | set(current)):
        before = previous.get(key)
        after = current.get(key)
        if before is None and after is None:  # pragma: no cover - 集合运算保证
            continue
        if before is None:
            changes.append(
                RelationChange(
                    counterparty=key,
                    kind=KIND_ADDED,
                    previous=None,
                    current=after,
                    delta=after,
                    sign_flip=False,
                    significant=True,
                )
            )
            continue
        if after is None:
            changes.append(
                RelationChange(
                    counterparty=key,
                    kind=KIND_REMOVED,
                    previous=before,
                    current=None,
                    delta=-before,
                    sign_flip=False,
                    significant=True,
                )
            )
            continue
        delta = after - before
        sign_flip = before * after < 0
        significant = abs(delta) > threshold or sign_flip
        if not significant:
            continue
        changes.append(
            RelationChange(
                counterparty=key,
                kind=KIND_CHANGED,
                previous=before,
                current=after,
                delta=delta,
                sign_flip=sign_flip,
                significant=True,
            )
        )
    changes.sort(key=lambda change: (-abs(change.delta or 0.0), change.counterparty))
    return changes


__all__ = [
    "KIND_ADDED",
    "KIND_CHANGED",
    "KIND_REMOVED",
    "RelationChange",
    "significant_changes",
]
