"""关系显著变化检测单测（AC4）：阈值可配、符号翻转、新增/消失。"""

import pytest

from app.analysis.core import relation_diff as diff


def _kinds(changes: list[diff.RelationChange]) -> dict[str, str]:
    return {change.counterparty: change.kind for change in changes}


def test_threshold_controls_significance() -> None:
    previous = {"A-USDT-SWAP": 0.5}
    current = {"A-USDT-SWAP": 0.75}
    assert diff.significant_changes(previous, current, threshold=0.3) == []
    strict = diff.significant_changes(previous, current, threshold=0.2)
    assert _kinds(strict) == {"A-USDT-SWAP": diff.KIND_CHANGED}
    assert strict[0].delta == pytest.approx(0.25)
    assert strict[0].sign_flip is False


def test_sign_flip_is_significant_regardless_of_magnitude() -> None:
    changes = diff.significant_changes({"A": 0.9}, {"A": -0.9}, threshold=100.0)
    assert _kinds(changes) == {"A": diff.KIND_CHANGED}
    assert changes[0].sign_flip is True
    assert changes[0].significant is True


def test_added_and_removed_edges_are_reported() -> None:
    changes = diff.significant_changes({"OLD": 0.4}, {"NEW": 0.6}, threshold=0.2)
    assert _kinds(changes) == {"OLD": diff.KIND_REMOVED, "NEW": diff.KIND_ADDED}
    removed = next(change for change in changes if change.kind == diff.KIND_REMOVED)
    added = next(change for change in changes if change.kind == diff.KIND_ADDED)
    assert removed.previous == pytest.approx(0.4)
    assert removed.current is None
    assert added.current == pytest.approx(0.6)
    assert added.previous is None


def test_no_change_returns_empty() -> None:
    assert diff.significant_changes({"A": 0.3}, {"A": 0.3}) == []
    assert diff.significant_changes({}, {}) == []


def test_changes_sorted_by_absolute_delta() -> None:
    changes = diff.significant_changes({"A": 0.0, "B": 0.0}, {"A": 0.9, "B": 0.3}, threshold=0.2)
    assert [change.counterparty for change in changes] == ["A", "B"]


def test_payload_shape() -> None:
    change = diff.significant_changes({"A": 0.1}, {"A": 0.9}, threshold=0.2)[0]
    assert change.as_payload() == {
        "counterparty": "A",
        "kind": diff.KIND_CHANGED,
        "previous": 0.1,
        "current": 0.9,
        "delta": pytest.approx(0.8),
        "sign_flip": False,
        "significant": True,
    }


def test_negative_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        diff.significant_changes({"A": 0.1}, {"A": 0.2}, threshold=-0.1)
