"""机会状态机：合法边全部接受，非法边全部拒绝（参数化覆盖每一条非法转移）。

状态集合固定为 `new / reviewed / adopted / rejected / expired`；合法边只有五条：
`new → reviewed`、`new → expired`、`reviewed → adopted`、`reviewed → rejected`、
`reviewed → expired`。其余每一对（含自己到自己、终态的任何出边）都必须抛
`ValidationError`，不接受「忽略本次变更」这种兜底。
"""

from __future__ import annotations

import pytest

from app.core import ValidationError
from app.opportunity import ALLOWED_TRANSITIONS, STATUSES, transition

LEGAL: tuple[tuple[str, str], ...] = (
    ("new", "reviewed"),
    ("new", "expired"),
    ("reviewed", "adopted"),
    ("reviewed", "rejected"),
    ("reviewed", "expired"),
)

ILLEGAL: tuple[tuple[str, str], ...] = tuple(
    (current, target)
    for current in STATUSES
    for target in STATUSES
    if (current, target) not in LEGAL
)


def test_status_set_is_the_documented_one() -> None:
    assert STATUSES == ("new", "reviewed", "adopted", "rejected", "expired")


def test_every_status_has_a_transition_row() -> None:
    """状态机不能有缺口：每个状态都在表里，终态是真的没有出边。"""

    assert set(ALLOWED_TRANSITIONS) == set(STATUSES)
    assert ALLOWED_TRANSITIONS["adopted"] == frozenset()
    assert ALLOWED_TRANSITIONS["rejected"] == frozenset()
    assert ALLOWED_TRANSITIONS["expired"] == frozenset()


def test_illegal_pairs_cover_every_remaining_edge() -> None:
    """`ILLEGAL` 是全部 25 对里去掉 5 条合法边剩下的 20 对，一条都没漏。"""

    assert len(LEGAL) + len(ILLEGAL) == len(STATUSES) ** 2
    assert len(ILLEGAL) == 20


@pytest.mark.parametrize(("current", "target"), LEGAL)
def test_legal_transitions_are_accepted(current: str, target: str) -> None:
    assert transition(current, target) == target


@pytest.mark.parametrize(("current", "target"), ILLEGAL)
def test_illegal_transitions_raise(current: str, target: str) -> None:
    with pytest.raises(ValidationError):
        transition(current, target)


@pytest.mark.parametrize("unknown", ["", "NEW", "archived", "done"])
def test_unknown_status_is_rejected_on_both_sides(unknown: str) -> None:
    with pytest.raises(ValidationError):
        transition(unknown, "reviewed")
    with pytest.raises(ValidationError):
        transition("new", unknown)
