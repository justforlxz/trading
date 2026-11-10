"""关系网络契约：节点、边、社区划分与网络指标。

网络的身份键是 `product_key`：同一产品的现货与永续是同一个标的在网络里的一次
出现，不对同一产品画两个节点。边的系数来自 T2.3 的相关矩阵，只做分析展示，
不承载策略编辑。

`edges` 里出现过的 `product_key` 必须全部出现在 `nodes` 里（无悬空边），
`min_abs_corr` 是裁边阈值，两边系数绝对值低于它的边不返回，也不返回自环。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import AssetType, Bar, DecimalString, UtcDatetime

__all__ = [
    "RelationCommunity",
    "RelationEdge",
    "RelationGraphResponse",
    "RelationNeighbor",
    "RelationNeighborsResponse",
    "RelationNode",
]


class RelationNode(BaseModel):
    """网络里的一个标的及其网络指标（度数、中心性、所属社区）。"""

    product_key: str
    asset_type: AssetType
    community_id: int
    degree: int
    centrality: DecimalString


class RelationEdge(BaseModel):
    """一条相关边；`samples` 是算这个系数时实际用到的样本条数。"""

    product_key_a: str
    product_key_b: str
    coefficient: DecimalString
    samples: int


class RelationCommunity(BaseModel):
    """一个社区：编号由社区划分算法给出，成员是标的的 `product_key`。"""

    community_id: int
    product_keys: list[str]


_EXAMPLE_NODES = [
    {
        "product_key": "AAPL",
        "asset_type": "tokenized_equity",
        "community_id": 0,
        "degree": 2,
        "centrality": "0.67",
    },
    {
        "product_key": "MSFT",
        "asset_type": "tokenized_equity",
        "community_id": 0,
        "degree": 2,
        "centrality": "0.67",
    },
    {
        "product_key": "NVDA",
        "asset_type": "tokenized_equity",
        "community_id": 1,
        "degree": 2,
        "centrality": "0.67",
    },
    {
        "product_key": "TSLA",
        "asset_type": "tokenized_equity",
        "community_id": 1,
        "degree": 1,
        "centrality": "0.33",
    },
]

_EXAMPLE_EDGES = [
    {
        "product_key_a": "AAPL",
        "product_key_b": "MSFT",
        "coefficient": "0.87",
        "samples": 60,
    },
    {
        "product_key_a": "AAPL",
        "product_key_b": "NVDA",
        "coefficient": "-0.64",
        "samples": 60,
    },
    {
        "product_key_a": "MSFT",
        "product_key_b": "NVDA",
        "coefficient": "-0.64",
        "samples": 60,
    },
    {
        "product_key_a": "NVDA",
        "product_key_b": "TSLA",
        "coefficient": "0.58",
        "samples": 60,
    },
]


class RelationGraphResponse(BaseModel):
    """一次请求返回一张完整的小图：节点、边、社区与图级平均连通度。"""

    as_of: UtcDatetime
    bar: Bar
    window: int
    min_abs_corr: DecimalString
    average_degree: DecimalString
    nodes: list[RelationNode]
    edges: list[RelationEdge]
    communities: list[RelationCommunity]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-10T00:00:00Z",
                    "bar": "1d",
                    "window": 60,
                    "min_abs_corr": "0.5",
                    "average_degree": "1.75",
                    "nodes": _EXAMPLE_NODES,
                    "edges": _EXAMPLE_EDGES,
                    "communities": [
                        {"community_id": 0, "product_keys": ["AAPL", "MSFT"]},
                        {"community_id": 1, "product_keys": ["NVDA", "TSLA"]},
                    ],
                }
            ]
        }
    )


class RelationNeighbor(BaseModel):
    """某个标的的邻居及其系数；按系数绝对值从大到小排列。"""

    product_key: str
    asset_type: AssetType
    coefficient: DecimalString
    samples: int


class RelationNeighborsResponse(BaseModel):
    product_key: str
    bar: Bar
    window: int
    items: list[RelationNeighbor]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "product_key": "AAPL",
                    "bar": "1d",
                    "window": 60,
                    "items": [
                        {
                            "product_key": "MSFT",
                            "asset_type": "tokenized_equity",
                            "coefficient": "0.87",
                            "samples": 60,
                        },
                        {
                            "product_key": "NVDA",
                            "asset_type": "tokenized_equity",
                            "coefficient": "-0.64",
                            "samples": 60,
                        },
                    ],
                }
            ]
        }
    )
