"""网络指标：度数、度中心性与平均连通度。

三个量都只由「节点集合 + 边集合」决定，纯函数、不读库。输入是**已经按阈值裁过**
的边：度数数的是画出来的边，不是所有相关系数。

口径（无自环时三者互相自洽）：

- 度数 = 与该节点相连的边数；
- 度中心性 = 度数 / (节点数 - 1)，只有一个节点时没有「别人」，记 0；
- 平均连通度 = 2E / V，度数之和等于两倍边数。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.core import InvariantViolation

__all__ = ["average_degree", "degree_centrality", "degrees"]


def degrees(nodes: Sequence[str], edges: Iterable[tuple[str, str]]) -> dict[str, int]:
    """每个节点连了几条边；没有边的节点记 0，不省略。

    自环与悬空端点都是构图错误，不是「用户传错了参数」，因此抛
    `InvariantViolation` 而不是静默计数：自环会让度数之和不再等于两倍边数，
    悬空端点会让 `edges` 里出现 `nodes` 里没有的标的。
    """

    counts = {node: 0 for node in nodes}
    for left, right in edges:
        if left == right:
            raise InvariantViolation(f"关系网络不允许自环:{left}")
        for node in (left, right):
            if node not in counts:
                raise InvariantViolation(f"关系网络的边连着图外的标的:{node}")
            counts[node] += 1
    return counts


def degree_centrality(degree: int, node_count: int) -> float:
    """度中心性：度数占「与其他所有节点都相连」的比例。

    只有一个节点时不存在可连的对象，记 0（而不是除以 0）。
    """

    if node_count <= 1:
        return 0.0
    return degree / (node_count - 1)


def average_degree(edge_count: int, node_count: int) -> float:
    """平均连通度 `2E / V`；没有节点时记 0。"""

    if node_count <= 0:
        return 0.0
    return 2.0 * edge_count / node_count
