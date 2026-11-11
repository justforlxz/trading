"""社区划分：把「一起涨跌的标的」分成社区，纯函数、不读库。

输入是已经按阈值裁过边的图，每条边带一个相关系数。规则两条：

- 只有**正**相关的边参与划分。负相关表示两者反向，放进同一个社区等于把对立
  关系说成同类；分隔符不传递分组，因此负边只影响度数，不影响社区。
- 标签传播：每个节点先自成一派，按节点名升序轮转，每轮把标签改成「邻居标签里
  权重和最大的那个」，同分时取标签名字典序最小的那个。轮转顺序、权重、同分规则
  都定死，因此同一份输入永远得到同一份划分。

轮次有上限：标签传播在极端图上可能来回震动，跑到上限就按当下的标签收口，
而不是无限循环。社区编号按「社区内最小成员」排序后从 0 开始，所以编号本身
也稳定。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

__all__ = ["MAX_ROUNDS", "communities"]

MAX_ROUNDS = 100


def communities(nodes: Sequence[str], edges: Iterable[tuple[str, str, float]]) -> dict[str, int]:
    """节点 → 社区编号。`edges` 的每条是 `(节点 A, 节点 B, 相关系数)`。

    没有任何正边的图（含空图、全负相关的图）每个节点各成一个社区：没有「一起
    涨跌」的证据，就不硬造分组。
    """

    ordered = tuple(nodes)
    neighbours: dict[str, list[tuple[str, float]]] = {node: [] for node in ordered}
    for left, right, coefficient in edges:
        if left == right or coefficient <= 0.0:
            continue
        if left not in neighbours or right not in neighbours:
            continue
        neighbours[left].append((right, coefficient))
        neighbours[right].append((left, coefficient))

    labels = {node: node for node in ordered}
    for _ in range(MAX_ROUNDS):
        changed = False
        for node in sorted(ordered):
            weights: dict[str, float] = {}
            for other, weight in neighbours[node]:
                label = labels[other]
                weights[label] = weights.get(label, 0.0) + weight
            if not weights:
                continue
            # 权重和最大者胜出；同分取标签名最小者，保证结果与邻居顺序无关。
            winner = min(weights.items(), key=lambda item: (-item[1], item[0]))[0]
            if winner != labels[node]:
                labels[node] = winner
                changed = True
        if not changed:
            break

    members: dict[str, list[str]] = {}
    for node in ordered:
        members.setdefault(labels[node], []).append(node)
    by_smallest_member = sorted(members, key=lambda label: min(members[label]))
    return {
        node: index for index, label in enumerate(by_smallest_member) for node in members[label]
    }
