"""构图：按阈值裁边、无自环、无悬空边，指标与社区的手算答案。

手算用例沿用契约示例那张四点图（四条边、两个社区）：

| 边 | 系数 | |系数| ≥ 0.5 |
| --- | --- | --- |
| AAPL-MSFT | +0.87 | 是 |
| AAPL-NVDA | -0.64 | 是 |
| MSFT-NVDA | -0.64 | 是 |
| NVDA-TSLA | +0.58 | 是 |

度数 AAPL 2 / MSFT 2 / NVDA 3 / TSLA 1，度数之和 8 = 2E，平均连通度 2E/V = 2，
中心性 = 度数 / 3；社区只由正边给出：{AAPL, MSFT} 与 {NVDA, TSLA}。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core import InvariantViolation
from app.market import Matrix
from app.relations import Graph, build_graph

AS_OF = datetime(2026, 11, 10, tzinfo=UTC)
NODES = ("AAPL", "MSFT", "NVDA", "TSLA")
ASSETS = {node: "tokenized_equity" for node in NODES}
PAIRS = {
    ("AAPL", "MSFT"): 0.87,
    ("AAPL", "NVDA"): -0.64,
    ("MSFT", "NVDA"): -0.64,
    ("NVDA", "TSLA"): 0.58,
}


def _matrix(
    pairs: dict[tuple[str, str], float | None],
    *,
    keys: tuple[str, ...] = NODES,
    samples: int = 60,
) -> Matrix:
    """按产品键构造一张对称矩阵；未给出的交叉格是「未定义」（`None`）。"""

    coefficients: dict[str, dict[str, float | None]] = {
        left: {right: (1.0 if left == right else None) for right in keys} for left in keys
    }
    counts: dict[tuple[str, str], int] = {(left, right): 0 for left in keys for right in keys}
    for (left, right), coefficient in pairs.items():
        coefficients[left][right] = coefficient
        coefficients[right][left] = coefficient
        counts[(left, right)] = samples
        counts[(right, left)] = samples
    return Matrix(
        symbols=tuple(keys),
        bar="1d",
        window=60,
        as_of=AS_OF,
        coefficients=coefficients,
        samples=counts,
    )


def _graph(
    min_abs_corr: float = 0.5,
    pairs: dict[tuple[str, str], float | None] | None = None,
) -> Graph:
    return build_graph(_matrix(PAIRS if pairs is None else pairs), ASSETS, min_abs_corr)


def test_known_four_node_graph() -> None:
    """节点、边、指标、社区逐项对上手算值。"""

    graph = _graph()

    assert graph.as_of == AS_OF
    assert graph.bar == "1d"
    assert graph.window == 60
    assert graph.min_abs_corr == 0.5
    assert [(row.product_key, row.degree) for row in graph.nodes] == [
        ("AAPL", 2),
        ("MSFT", 2),
        ("NVDA", 3),
        ("TSLA", 1),
    ]
    assert [row.centrality for row in graph.nodes] == pytest.approx([2 / 3, 2 / 3, 1.0, 1 / 3])
    assert graph.average_degree == 2.0
    assert [(row.product_key_a, row.product_key_b) for row in graph.edges] == [
        ("AAPL", "MSFT"),
        ("AAPL", "NVDA"),
        ("MSFT", "NVDA"),
        ("NVDA", "TSLA"),
    ]
    assert [row.community_id for row in graph.nodes] == [0, 0, 1, 1]
    assert [(row.community_id, row.product_keys) for row in graph.communities] == [
        (0, ("AAPL", "MSFT")),
        (1, ("NVDA", "TSLA")),
    ]


def test_graph_invariants_hold_for_every_edge() -> None:
    """三条硬约束：系数不低于阈值、无自环、无悬空边。"""

    graph = _graph(min_abs_corr=0.6)

    keys = {row.product_key for row in graph.nodes}
    for edge in graph.edges:
        assert abs(edge.coefficient) >= graph.min_abs_corr
        assert edge.product_key_a != edge.product_key_b
        assert edge.product_key_a in keys
        assert edge.product_key_b in keys


def test_threshold_is_inclusive_on_the_boundary() -> None:
    """恰好等于阈值的边保留（判据是 `>=`），低于阈值一个 epsilon 的边裁掉。"""

    graph = _graph(min_abs_corr=0.58)

    assert ("NVDA", "TSLA") in [(row.product_key_a, row.product_key_b) for row in graph.edges]

    dropped = _graph(min_abs_corr=0.581)

    assert ("NVDA", "TSLA") not in [(row.product_key_a, row.product_key_b) for row in dropped.edges]


def test_undefined_coefficient_paints_no_edge() -> None:
    """样本不足的格子是 `None`：不画边，也不拿 0 顶替。"""

    graph = _graph(pairs={("AAPL", "MSFT"): None})

    assert graph.edges == ()
    assert [row.degree for row in graph.nodes] == [0, 0, 0, 0]


def test_diagonal_never_becomes_an_edge() -> None:
    """对角线是与自己的相关（1.0），永远不进边集合。"""

    graph = _graph()

    assert all(row.product_key_a != row.product_key_b for row in graph.edges)


def test_high_threshold_leaves_every_node_isolated() -> None:
    """阈值高于所有系数时：节点仍在图里，边一条不剩。"""

    graph = _graph(min_abs_corr=1.0)

    assert [row.product_key for row in graph.nodes] == list(NODES)
    assert graph.edges == ()
    assert graph.average_degree == 0.0
    assert len(graph.communities) == len(NODES)


def test_missing_asset_type_is_a_composition_error() -> None:
    """资产类别缺失属于构图错误：直接报错，不默认成某一种资产。"""

    with pytest.raises(InvariantViolation):
        build_graph(_matrix(PAIRS), {"AAPL": "tokenized_equity"}, 0.5)


def test_empty_matrix_gives_an_empty_graph() -> None:
    """没有节点时三份集合都为空，平均连通度为 0。"""

    matrix = Matrix(
        symbols=(),
        bar="1d",
        window=60,
        as_of=AS_OF,
        coefficients={},
        samples={},
    )

    graph = build_graph(matrix, {}, 0.5)

    assert graph.nodes == ()
    assert graph.edges == ()
    assert graph.communities == ()
    assert graph.average_degree == 0.0


def test_single_node_matrix_has_no_edges() -> None:
    """一个节点只有对角线，没有任何边。"""

    graph = build_graph(_matrix({}, keys=("AAPL",)), {"AAPL": "crypto"}, 0.5)

    assert [(row.product_key, row.degree, row.centrality) for row in graph.nodes] == [
        ("AAPL", 0, 0.0)
    ]
    assert graph.edges == ()


def test_samples_come_from_the_matrix_cell() -> None:
    """边的条数取矩阵里该格实际用到的条数，不另行估算。"""

    graph = build_graph(_matrix(PAIRS, samples=42), ASSETS, 0.5)

    assert {row.samples for row in graph.edges} == {42}
