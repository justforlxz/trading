"""策略状态机（纯函数，无 IO）。

状态与动作的对应关系是唯一真值表：除表内列出的迁移外一律非法。
调用方（`service.transition`）负责在非法迁移时拒绝写库，因此这里不碰数据库。
"""

from typing import Final

DRAFT: Final = "draft"
PENDING_APPROVAL: Final = "pending_approval"
APPROVED: Final = "approved"
REJECTED: Final = "rejected"
ARCHIVED: Final = "archived"

STATUSES: Final[tuple[str, ...]] = (
    DRAFT,
    PENDING_APPROVAL,
    APPROVED,
    REJECTED,
    ARCHIVED,
)

SUBMIT: Final = "submit"
APPROVE: Final = "approve"
REJECT: Final = "reject"
ARCHIVE: Final = "archive"

ACTIONS: Final[tuple[str, ...]] = (SUBMIT, APPROVE, REJECT, ARCHIVE)

TRANSITIONS: Final[dict[str, dict[str, str]]] = {
    DRAFT: {SUBMIT: PENDING_APPROVAL},
    PENDING_APPROVAL: {APPROVE: APPROVED, REJECT: REJECTED},
    APPROVED: {ARCHIVE: ARCHIVED},
    REJECTED: {ARCHIVE: ARCHIVED},
    ARCHIVED: {},
}

# 只有这两个状态允许编辑内容；一旦进入审批或已通过，内容必须冻结。
EDITABLE_STATUSES: Final[frozenset[str]] = frozenset({DRAFT, REJECTED})


class IllegalTransition(Exception):
    """非法的 `(状态, 动作)` 组合；`code` 直接用于 API 错误体。"""

    code = "strategy_illegal_transition"

    def __init__(self, current: str, action: str) -> None:
        self.current = current
        self.action = action
        super().__init__(f"cannot {action} a strategy in status {current}")


def next_status(current: str, action: str) -> str:
    """返回迁移后的状态；表内没有的组合一律抛 `IllegalTransition`。"""

    allowed = TRANSITIONS.get(current)
    if allowed is None:
        raise IllegalTransition(current, action)
    target = allowed.get(action)
    if target is None:
        raise IllegalTransition(current, action)
    return target


def is_editable(status: str) -> bool:
    return status in EDITABLE_STATUSES


__all__ = [
    "ACTIONS",
    "APPROVE",
    "APPROVED",
    "ARCHIVE",
    "ARCHIVED",
    "DRAFT",
    "EDITABLE_STATUSES",
    "PENDING_APPROVAL",
    "REJECT",
    "REJECTED",
    "STATUSES",
    "SUBMIT",
    "TRANSITIONS",
    "IllegalTransition",
    "is_editable",
    "next_status",
]
