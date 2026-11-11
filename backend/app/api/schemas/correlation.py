"""相关性与横截面契约：相关矩阵、滚动相关序列、市场广度与共振。

一个产品的现货与永续在分析层是同一个标的，因此相关性的身份键是 `product_key`
（`app.instrument.model.Instrument.product_key` 的配对键），不是 `instId`。

样本不足的格子如实写 `null`，不插值、不补造；横截面严格按类别分开统计
（`inst_type` 必填），两类标的的交易时段不同，不混在一个统计里。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    Bar,
    DecimalString,
    InstType,
    UtcDatetime,
)

__all__ = [
    "CorrelationCell",
    "CorrelationMatrixResponse",
    "CorrelationPoint",
    "CorrelationSeriesResponse",
    "MarketBreadth",
    "MarketOverviewResponse",
    "MarketResonance",
]


class CorrelationCell(BaseModel):
    """矩阵的一格；`coefficient` 为 `null` 表示该格样本不足。"""

    product_key_a: str
    product_key_b: str
    coefficient: DecimalString | None
    samples: int


_EXAMPLE_CELLS = [
    {
        "product_key_a": "AAPL",
        "product_key_b": "AAPL",
        "coefficient": "1",
        "samples": 60,
    },
    {
        "product_key_a": "AAPL",
        "product_key_b": "MSFT",
        "coefficient": "0.87",
        "samples": 60,
    },
    {
        "product_key_a": "AAPL",
        "product_key_b": "NVDA",
        "coefficient": None,
        "samples": 2,
    },
    {
        "product_key_a": "MSFT",
        "product_key_b": "AAPL",
        "coefficient": "0.87",
        "samples": 60,
    },
    {
        "product_key_a": "MSFT",
        "product_key_b": "MSFT",
        "coefficient": "1",
        "samples": 60,
    },
    {
        "product_key_a": "MSFT",
        "product_key_b": "NVDA",
        "coefficient": "0.64",
        "samples": 60,
    },
    {
        "product_key_a": "NVDA",
        "product_key_b": "AAPL",
        "coefficient": None,
        "samples": 2,
    },
    {
        "product_key_a": "NVDA",
        "product_key_b": "MSFT",
        "coefficient": "0.64",
        "samples": 60,
    },
    {
        "product_key_a": "NVDA",
        "product_key_b": "NVDA",
        "coefficient": "1",
        "samples": 60,
    },
]


class CorrelationMatrixResponse(BaseModel):
    """某一时点、某一周期、某一窗口的整张相关矩阵（格子全量给出，含对角线）。"""

    bar: Bar
    window: int
    as_of: UtcDatetime
    product_keys: list[str]
    cells: list[CorrelationCell]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "bar": "1d",
                    "window": 60,
                    "as_of": "2026-11-10T00:00:00Z",
                    "product_keys": ["AAPL", "MSFT", "NVDA"],
                    "cells": _EXAMPLE_CELLS,
                }
            ]
        }
    )


class CorrelationPoint(BaseModel):
    """滚动相关序列上的一个点；样本不足时 `coefficient` 为 `null`。"""

    as_of: UtcDatetime
    coefficient: DecimalString | None
    samples: int


class CorrelationSeriesResponse(BaseModel):
    """两个标的在滚动窗口上的相关性随时间的变化。"""

    product_key_a: str
    product_key_b: str
    bar: Bar
    window: int
    available_from: UtcDatetime | None = None
    available_to: UtcDatetime | None = None
    points: list[CorrelationPoint]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "product_key_a": "AAPL",
                    "product_key_b": "MSFT",
                    "bar": "1d",
                    "window": 30,
                    "available_from": "2026-10-01T00:00:00Z",
                    "available_to": "2026-11-10T00:00:00Z",
                    "points": [
                        {
                            "as_of": "2026-11-08T00:00:00Z",
                            "coefficient": "0.83",
                            "samples": 30,
                        },
                        {
                            "as_of": "2026-11-09T00:00:00Z",
                            "coefficient": "0.85",
                            "samples": 30,
                        },
                        {
                            "as_of": "2026-11-10T00:00:00Z",
                            "coefficient": "0.87",
                            "samples": 30,
                        },
                    ],
                }
            ]
        }
    )


class MarketBreadth(BaseModel):
    """某一类别在某一时点上的涨跌家数。

    `ratio` 是上涨家数除以下跌家数；没有下跌标的时除以零不成立，如实给 `null`，
    不写成无穷大或一个很大的数。`unchanged` 是涨跌幅恰好为零的标的数。
    """

    advancers: int
    decliners: int
    unchanged: int
    ratio: DecimalString | None
    participants: int


class MarketResonance(BaseModel):
    """同一类别内部的同向程度：全部同向上涨为 1，涨跌各半为 0，恒在 [0, 1]。

    参与标的少于 5 个时不给数（`strength` 为 `null`）：样本不足时的「共振强度」
    没有意义，编一个数字比留空更糟。
    """

    strength: DecimalString | None
    participants: int
    window: int


class MarketOverviewResponse(BaseModel):
    """某一类别（`inst_type`）的横截面总览；两类标的各自统计，互不混入。"""

    inst_type: InstType
    bar: Bar
    as_of: UtcDatetime
    breadth: MarketBreadth
    resonance: MarketResonance

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inst_type": "SPOT",
                    "bar": "1d",
                    "as_of": "2026-11-10T00:00:00Z",
                    "breadth": {
                        "advancers": 8,
                        "decliners": 2,
                        "unchanged": 1,
                        "ratio": "4",
                        "participants": 11,
                    },
                    "resonance": {
                        "strength": "0.62",
                        "participants": 11,
                        "window": 20,
                    },
                }
            ]
        }
    )
