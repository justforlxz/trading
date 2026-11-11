"""关系网络：节点是标的（产品键），边是相关性，带社区划分与网络指标。

本包只做分析展示：不产生交易意图，不写库，也不承担策略编辑。跨包调用一律走本
门面，不允许 `from app.relations.graph import ...` 之类的子模块直连。

图里的产品与「读哪条腿的 K 线」在 `relation_graph` 里一次定死：同一产品的现货与
永续是同一次出现，不会各画一个节点。
"""

from app.relations.cluster import communities
from app.relations.graph import Community, Edge, Graph, Node, build_graph, relation_graph
from app.relations.metrics import average_degree, degree_centrality, degrees

__all__ = [
    "Community",
    "Edge",
    "Graph",
    "Node",
    "average_degree",
    "build_graph",
    "communities",
    "degree_centrality",
    "degrees",
    "relation_graph",
]
