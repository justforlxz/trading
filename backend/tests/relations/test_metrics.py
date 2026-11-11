"""网络指标：度数、度中心性、平均连通度的手算答案与边界。

四条判据互相自洽：没有边就没有度数、度数之和等于两倍边数、中心性不超过 1、
只有一个节点时平均连通度与中心性都是 0。
"""

from __future__ import annotations

import pytest

from app.core import InvariantViolation
from app.relations import average_degree, degree_centrality, degrees

NODES = ("AAPL", "MSFT", "NVDA", "TSLA")
EDGES = (
    ("AAPL", "MSFT"),
    ("AAPL", "NVDA"),
    ("MSFT", "NVDA"),
    ("NVDA", "TSLA"),
)


def test_degrees_count_both_ends_and_keep_isolated_nodes() -> None:
    """每条边给两端各加 1；没有边的节点记 0，不在结果里消失。"""

    counts = degrees(NODES, EDGES)

    assert counts == {"AAPL": 2, "MSFT": 2, "NVDA": 3, "TSLA": 1}
    assert sum(counts.values()) == 2 * len(EDGES)


def test_degrees_of_isolated_graph() -> None:
    """没有边时每个节点都是 0，不是缺失键。"""

    assert degrees(("AAPL", "MSFT"), ()) == {"AAPL": 0, "MSFT": 0}


def test_self_loop_is_rejected() -> None:
    """自环会让度数之和不再等于两倍边数，必须报错而不是计数。"""

    with pytest.raises(InvariantViolation):
        degrees(("AAPL",), (("AAPL", "AAPL"),))


def test_edge_to_unknown_node_is_rejected() -> None:
    """悬空端点等于「edges 里有 nodes 里没有的标的」，必须报错。"""

    with pytest.raises(InvariantViolation):
        degrees(("AAPL",), (("AAPL", "NVDA"),))


def test_degree_centrality_is_degree_over_other_nodes() -> None:
    """四个节点时 3 度是满值 1，2 度是 2/3，1 度是 1/3。"""

    assert degree_centrality(3, 4) == 1.0
    assert degree_centrality(2, 4) == pytest.approx(2 / 3)
    assert degree_centrality(1, 4) == pytest.approx(1 / 3)
    assert degree_centrality(0, 4) == 0.0


def test_degree_centrality_of_single_node_is_zero() -> None:
    """只有一个节点时没有可连的对象，不能除以 0。"""

    assert degree_centrality(0, 1) == 0.0
    assert degree_centrality(0, 0) == 0.0


def test_average_degree_is_twice_edges_over_nodes() -> None:
    """四条边四个节点 → 平均连通度 2；一条边两个节点 → 1。"""

    assert average_degree(4, 4) == 2.0
    assert average_degree(1, 2) == 1.0
    assert average_degree(0, 3) == 0.0


def test_average_degree_of_empty_graph_is_zero() -> None:
    """空图没有可平均的对象，记 0 而不是除以 0。"""

    assert average_degree(0, 0) == 0.0
