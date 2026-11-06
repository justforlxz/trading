"""策略状态机（AC4）：合法路径、非法迁移与可编辑状态都是纯函数行为。"""

import pytest

from app.strategy.state_machine import (
    ACTIONS,
    APPROVED,
    ARCHIVED,
    DRAFT,
    EDITABLE_STATUSES,
    PENDING_APPROVAL,
    REJECTED,
    STATUSES,
    IllegalTransition,
    is_editable,
    next_status,
)

LEGAL = {
    (DRAFT, "submit"): PENDING_APPROVAL,
    (PENDING_APPROVAL, "approve"): APPROVED,
    (PENDING_APPROVAL, "reject"): REJECTED,
    (APPROVED, "archive"): ARCHIVED,
    (REJECTED, "archive"): ARCHIVED,
}


def test_legal_path_reaches_approved_and_archived() -> None:
    status = DRAFT
    for action in ("submit", "approve", "archive"):
        status = next_status(status, action)
    assert status == ARCHIVED

    status = DRAFT
    for action in ("submit", "reject", "archive"):
        status = next_status(status, action)
    assert status == ARCHIVED


@pytest.mark.parametrize(
    ("status", "action"),
    [(status, action) for status in STATUSES for action in ACTIONS],
)
def test_every_status_action_pair_matches_the_table(status: str, action: str) -> None:
    expected = LEGAL.get((status, action))
    if expected is not None:
        assert next_status(status, action) == expected
        return

    with pytest.raises(IllegalTransition) as caught:
        next_status(status, action)
    assert caught.value.code == "strategy_illegal_transition"
    assert caught.value.current == status
    assert caught.value.action == action


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (DRAFT, "approve"),
        (DRAFT, "reject"),
        (DRAFT, "archive"),
        (REJECTED, "submit"),
        (APPROVED, "submit"),
        (ARCHIVED, "archive"),
    ],
)
def test_known_illegal_edges_are_rejected(status: str, action: str) -> None:
    with pytest.raises(IllegalTransition):
        next_status(status, action)


def test_only_draft_and_rejected_are_editable() -> None:
    assert frozenset({DRAFT, REJECTED}) == EDITABLE_STATUSES
    for status in STATUSES:
        assert is_editable(status) is (status in (DRAFT, REJECTED))
    assert is_editable(PENDING_APPROVAL) is False
    assert is_editable(APPROVED) is False
    assert is_editable(ARCHIVED) is False
