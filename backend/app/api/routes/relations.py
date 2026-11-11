"""关系网络端点：整图与单标的邻居。

端点只做入参校验与响应组装；构图、社区划分与网络指标都在 `app.relations` 里。
系数与网络指标按 4 位小数量化后再出接口：契约只要求十进制字符串，位数在这一处
统一，因此同一份数据两次请求得到逐字节相同的 JSON。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from app.api.mapping import decimal_str
from app.api.schemas import (
    RelationCommunity,
    RelationEdge,
    RelationGraphResponse,
    RelationNeighbor,
    RelationNeighborsResponse,
    RelationNode,
)
from app.api.schemas.common import Bar
from app.core import ValidationError
from app.instrument import get_instrument_pair
from app.relations import Community, Edge, Node, relation_graph

__all__ = ["relations_router"]

relations_router = APIRouter(tags=["relations"])

# 相关系数与比值类指标统一量化到 4 位小数（与自选「相关标的」同口径）。
_RATIO_PLACES = Decimal("0.0001")


@relations_router.get("/relations/graph", response_model=RelationGraphResponse)
def get_relation_graph(
    bar: Bar = Query(...),
    window: int = Query(..., ge=2, le=250),
    min_abs_corr: float = Query(0.5, ge=0, le=1),
    as_of: AwareDatetime | None = Query(None),
) -> RelationGraphResponse:
    """自选范围内的整张关系网络；`as_of` 缺省取库里最后一根 K 线。"""

    graph = relation_graph(bar, window, min_abs_corr, as_of)
    return RelationGraphResponse(
        as_of=graph.as_of,
        bar=graph.bar,
        window=graph.window,
        min_abs_corr=_ratio(graph.min_abs_corr),
        average_degree=_ratio(graph.average_degree),
        nodes=[_node(row) for row in graph.nodes],
        edges=[_edge(row) for row in graph.edges],
        communities=[_community(row) for row in graph.communities],
    )


@relations_router.get("/relations/neighbors", response_model=RelationNeighborsResponse)
def get_relation_neighbors(
    product_key: str = Query(...),
    bar: Bar = Query(...),
    window: int = Query(..., ge=2, le=250),
    min_abs_corr: float = Query(0.5, ge=0, le=1),
) -> RelationNeighborsResponse:
    """某个产品的邻居，按系数绝对值从大到小、同值按产品键排列。

    邻居来自与整图同一张网络（同样的产品范围与阈值）；产品已登记但不在网络里时
    返回空列表——「没有被跟踪」与「没有相关标的」是两件事，只有前者查不到产品。
    """

    key = _known_product_key(product_key)
    graph = relation_graph(bar, window, min_abs_corr, None)
    asset_types = {row.product_key: row.asset_type for row in graph.nodes}
    neighbours = sorted(
        (row for row in graph.edges if key in (row.product_key_a, row.product_key_b)),
        key=lambda row: (-abs(row.coefficient), _other(row, key)),
    )
    return RelationNeighborsResponse(
        product_key=key,
        bar=bar,
        window=window,
        items=[
            RelationNeighbor(
                product_key=_other(row, key),
                asset_type=asset_types[_other(row, key)],
                coefficient=_ratio(row.coefficient),
                samples=row.samples,
            )
            for row in neighbours
        ],
    )


def _known_product_key(raw: str) -> str:
    """把调用方给的标识解析成产品键；未知标的按 404 处理（与自选相关标的同口径）。"""

    try:
        return get_instrument_pair(raw).product_key
    except ValidationError:
        raise HTTPException(status_code=404, detail=f"未找到产品 {raw.strip().upper()}") from None


def _other(edge: Edge, key: str) -> str:
    """一条边的另一端；两端相同的自环在构图时就已被拒绝。"""

    return edge.product_key_b if edge.product_key_a == key else edge.product_key_a


def _ratio(value: float) -> str:
    """浮点比值 → 4 位小数的十进制字符串，去掉尾随 0。"""

    return decimal_str(Decimal(str(value)).quantize(_RATIO_PLACES, rounding=ROUND_HALF_UP))


def _node(row: Node) -> RelationNode:
    return RelationNode(
        product_key=row.product_key,
        asset_type=row.asset_type,
        community_id=row.community_id,
        degree=row.degree,
        centrality=_ratio(row.centrality),
    )


def _edge(row: Edge) -> RelationEdge:
    return RelationEdge(
        product_key_a=row.product_key_a,
        product_key_b=row.product_key_b,
        coefficient=_ratio(row.coefficient),
        samples=row.samples,
    )


def _community(row: Community) -> RelationCommunity:
    return RelationCommunity(
        community_id=row.community_id,
        product_keys=list(row.product_keys),
    )
