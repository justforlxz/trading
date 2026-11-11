"""关系网络构图：节点是标的（产品键），边是相关性，按阈值裁边。

纯计算与取数分开，与 `app.market.matrix` 的分工一致：

- `build_graph` 只吃已经算好的相关矩阵与资产类别，不读库、不判断标的身份；
- `relation_graph` 负责「图里有哪些产品、每个产品读哪条腿的 K 线、按哪个时刻」。

网络的身份键是产品键：同一产品的现货与永续在网络里是同一次出现，不画两个节点。
边只保留绝对值不低于阈值的系数，不含自环；系数未定义（样本不足）的格子不画边，
也不拿 0 顶替。

只做分析展示：本模块不产生交易意图，也不写库。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core import InvariantViolation
from app.instrument import get_instrument_pair
from app.market import Matrix, correlation_matrix, data_range
from app.relations.cluster import communities
from app.relations.metrics import average_degree, degree_centrality, degrees
from app.watchlist import tracked_instruments

__all__ = [
    "Community",
    "Edge",
    "Graph",
    "Node",
    "build_graph",
    "relation_graph",
]


@dataclass(frozen=True, slots=True)
class Node:
    """网络里的一个标的及其网络指标。"""

    product_key: str
    asset_type: str
    community_id: int
    degree: int
    centrality: float


@dataclass(frozen=True, slots=True)
class Edge:
    """一条相关边；两端按产品键升序排列，`samples` 是算这个系数实际用到的条数。"""

    product_key_a: str
    product_key_b: str
    coefficient: float
    samples: int


@dataclass(frozen=True, slots=True)
class Community:
    """一个社区：编号由 `app.relations.cluster` 给出，成员按产品键升序。"""

    community_id: int
    product_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Graph:
    """一张完整的小图：节点、边、社区与图级平均连通度。"""

    as_of: datetime
    bar: str
    window: int
    min_abs_corr: float
    average_degree: float
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    communities: tuple[Community, ...]


def build_graph(
    matrix: Matrix,
    asset_types: Mapping[str, str],
    min_abs_corr: float,
) -> Graph:
    """把相关矩阵裁成关系网络：按阈值丢边、按产品键排序、算指标与社区。

    `matrix` 的标识必须是产品键（`relation_graph` 会把交易所标识换过来）。节点是
    矩阵里出现的全部产品，包括一条边都没有的那些——「跟踪了但和谁都不相关」本身
    是结论，不该因为没画线就从图里消失。
    """

    keys = tuple(sorted(matrix.symbols))
    missing = [key for key in keys if key not in asset_types]
    if missing:
        raise InvariantViolation(f"关系网络缺少这些产品的资产类别:{missing}")

    edges: list[Edge] = []
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            coefficient = matrix[left][right]
            if coefficient is None or abs(coefficient) < min_abs_corr:
                continue
            edges.append(Edge(left, right, coefficient, matrix.sample_size(left, right)))

    degree_of = degrees(keys, [(edge.product_key_a, edge.product_key_b) for edge in edges])
    community_of = communities(
        keys,
        [(edge.product_key_a, edge.product_key_b, edge.coefficient) for edge in edges],
    )

    nodes = tuple(
        Node(
            product_key=key,
            asset_type=asset_types[key],
            community_id=community_of[key],
            degree=degree_of[key],
            centrality=degree_centrality(degree_of[key], len(keys)),
        )
        for key in keys
    )
    return Graph(
        as_of=matrix.as_of,
        bar=matrix.bar,
        window=matrix.window,
        min_abs_corr=min_abs_corr,
        average_degree=average_degree(len(edges), len(keys)),
        nodes=nodes,
        edges=tuple(edges),
        communities=_grouped(nodes),
    )


def relation_graph(
    bar: str,
    window: int,
    min_abs_corr: float,
    as_of: datetime | None,
) -> Graph:
    """当前自选范围内的关系网络。

    图里的产品就是自选里跟踪的产品——自选是当下唯一的用户级标的集合，全市场扫描
    属于后续的市场驱动机会发现（T3.4）。一个产品只用一条腿读 K 线：优先永续
    （全天候有行情，也是策略执行的主形态），没有永续才用现货；两种形态不在同一张
    图里各画一个节点。

    `as_of` 缺省取这些标的在库里的最后一根 K 线：同一份库连读两次得到同一个时刻，
    因此响应内容逐字节相同，不以「请求时刻」为锚。
    """

    universe = _universe()
    moment = as_of if as_of is not None else _latest_open_time(universe, bar)
    if not universe:
        return _empty_graph(bar, window, min_abs_corr, moment)

    matrix = correlation_matrix([symbol for symbol, _ in universe.values()], bar, window, moment)
    return build_graph(
        _by_product_key(matrix, universe),
        {key: asset_type for key, (_, asset_type) in universe.items()},
        min_abs_corr,
    )


def _universe() -> dict[str, tuple[str, str]]:
    """产品键 → (读哪条腿的交易所标识, 资产类别)；顺序按产品键固定。

    同一产品的两种形态都由 `app.instrument` 的门面挑一次，本模块不自己按
    `symbol` 排序挑一行——那会得到与标的解析不一致的第二套规则。
    """

    universe: dict[str, tuple[str, str]] = {}
    for key in sorted({row.product_key for row in tracked_instruments()}):
        pair = get_instrument_pair(key)
        leg = pair.swap or pair.spot
        if leg is None:
            raise InvariantViolation(f"产品 {key} 既没有现货也没有永续, 无法取行情")
        universe[key] = (leg.symbol, leg.asset_type)
    return universe


def _latest_open_time(universe: Mapping[str, tuple[str, str]], bar: str) -> datetime:
    """缺省 `as_of`：这些标的在库里的最后一根 K 线。

    一根 K 线都没有时用当前时刻——此时图必然是空的，不存在两次不一致的内容。
    """

    latest = [
        found[1]
        for symbol, _ in universe.values()
        if (found := data_range(symbol, bar)) is not None
    ]
    return max(latest) if latest else datetime.now(UTC).replace(microsecond=0)


def _by_product_key(matrix: Matrix, universe: Mapping[str, tuple[str, str]]) -> Matrix:
    """把按交易所标识算出的矩阵换成按产品键标识。

    一条腿对应一个产品，映射是一对一（`_universe` 已按产品去重），因此换键不会
    把两个标的折成一个。系数与条数原样搬运，不做任何重算。
    """

    keys = {symbol: key for key, (symbol, _) in universe.items()}
    return Matrix(
        symbols=tuple(keys[symbol] for symbol in matrix.symbols),
        bar=matrix.bar,
        window=matrix.window,
        as_of=matrix.as_of,
        coefficients={
            keys[left]: {keys[right]: value for right, value in row.items()}
            for left, row in matrix.coefficients.items()
        },
        samples={
            (keys[left], keys[right]): count for (left, right), count in matrix.samples.items()
        },
    )


def _empty_graph(bar: str, window: int, min_abs_corr: float, as_of: datetime) -> Graph:
    """自选为空时的图：没有节点也没有边，不拿别人的标的凑一张图。"""

    return Graph(
        as_of=as_of,
        bar=bar,
        window=window,
        min_abs_corr=min_abs_corr,
        average_degree=0.0,
        nodes=(),
        edges=(),
        communities=(),
    )


def _grouped(nodes: Sequence[Node]) -> tuple[Community, ...]:
    """按社区编号把节点折成社区；编号已在 `cluster.communities` 里排好。"""

    members: dict[int, list[str]] = {}
    for node in nodes:
        members.setdefault(node.community_id, []).append(node.product_key)
    return tuple(
        Community(community_id, tuple(members[community_id])) for community_id in sorted(members)
    )
