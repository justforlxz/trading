"""社区划分：固定小图的已知答案、负相关不算同类、编号与结果稳定。

手算用例沿用契约示例那张四点图：

- AAPL-MSFT  +0.87（同向）
- AAPL-NVDA  -0.64（反向）
- MSFT-NVDA  -0.64（反向）
- NVDA-TSLA  +0.58（同向）

同向的两条边把四个点分成 {AAPL, MSFT} 与 {NVDA, TSLA}；负边只影响度数，不影响分组。
"""

from __future__ import annotations

from app.relations import communities

NODES = ("AAPL", "MSFT", "NVDA", "TSLA")
EDGES = (
    ("AAPL", "MSFT", 0.87),
    ("AAPL", "NVDA", -0.64),
    ("MSFT", "NVDA", -0.64),
    ("NVDA", "TSLA", 0.58),
)


def test_two_positive_edges_split_the_graph_in_two() -> None:
    """同向关系各自成组，编号按社区内最小成员从 0 起排。"""

    assert communities(NODES, EDGES) == {"AAPL": 0, "MSFT": 0, "NVDA": 1, "TSLA": 1}


def test_negative_edges_do_not_group() -> None:
    """只有负相关的两点各自成组：反向关系不是「一起涨跌」。"""

    mapping = communities(("AAPL", "MSFT"), (("AAPL", "MSFT", -0.8),))

    assert mapping == {"AAPL": 0, "MSFT": 1}


def test_isolated_node_gets_its_own_community() -> None:
    """没有边的节点自成一派，且不占用别人的编号。"""

    mapping = communities(
        ("AAPL", "MSFT", "TSLA"),
        (("AAPL", "MSFT", 0.9),),
    )

    assert mapping == {"AAPL": 0, "MSFT": 0, "TSLA": 1}


def test_empty_graph_has_no_communities() -> None:
    """空图没有节点，也就没有社区。"""

    assert communities((), ()) == {}


def test_single_node_is_one_community() -> None:
    assert communities(("AAPL",), ()) == {"AAPL": 0}


def test_same_input_gives_the_same_partition() -> None:
    """同一份输入连算两次结果一致：构图与社区划分都不依赖调用顺序或时间。"""

    first = communities(NODES, EDGES)
    second = communities(NODES, EDGES)

    assert first == second


def test_node_order_does_not_change_the_partition() -> None:
    """节点与边的输入顺序不改变划分：轮转按节点名升序、同分按标签名取小。"""

    shuffled = communities(tuple(reversed(NODES)), tuple(reversed(EDGES)))

    assert shuffled == communities(NODES, EDGES)


def test_edges_to_unknown_nodes_are_ignored() -> None:
    """图外的边不参与划分：构图已经保证无悬空边，这里只防越界索引。"""

    mapping = communities(("AAPL", "MSFT"), (("AAPL", "NOPE", 0.9),))

    assert mapping == {"AAPL": 0, "MSFT": 1}


def test_single_edge_between_two_nodes_groups_them() -> None:
    """最小正例：一条正边把两个节点并成一个社区。"""

    assert communities(("AAPL", "MSFT"), (("AAPL", "MSFT", 0.01),)) == {
        "AAPL": 0,
        "MSFT": 0,
    }
