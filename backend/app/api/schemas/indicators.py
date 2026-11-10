"""技术指标契约：指标目录（自描述）与按标的/周期的指标序列。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    Bar,
    DecimalString,
    InstType,
    ParamSpec,
    ParamValue,
    UtcDatetime,
)

__all__ = [
    "IndicatorCatalogResponse",
    "IndicatorDefinition",
    "IndicatorPoint",
    "IndicatorSeries",
    "IndicatorSeriesResponse",
]


class IndicatorDefinition(BaseModel):
    """单个指标的元数据：参数、输出字段、最小数据长度。"""

    name: str
    title: str
    summary: str
    params: list[ParamSpec]
    outputs: list[str]
    min_bars: int


class IndicatorCatalogResponse(BaseModel):
    items: list[IndicatorDefinition]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "name": "rsi",
                            "title": "RSI",
                            "summary": "相对强弱指标: 衡量近期涨跌幅度之比。",
                            "params": [
                                {
                                    "name": "period",
                                    "title": "周期",
                                    "kind": "int",
                                    "default": 14,
                                    "minimum": 2,
                                    "maximum": 200,
                                }
                            ],
                            "outputs": ["rsi"],
                            "min_bars": 15,
                        }
                    ]
                }
            ]
        }
    )


class IndicatorPoint(BaseModel):
    time: UtcDatetime
    values: dict[str, DecimalString | None]


class IndicatorSeries(BaseModel):
    name: str
    params: dict[str, ParamValue]
    points: list[IndicatorPoint]


class IndicatorSeriesResponse(BaseModel):
    inst_id: str
    inst_type: InstType
    bar: Bar
    series: list[IndicatorSeries]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inst_id": "XAAPL-USDT",
                    "inst_type": "SPOT",
                    "bar": "1h",
                    "series": [
                        {
                            "name": "rsi",
                            "params": {"period": 14},
                            "points": [
                                {"time": "2026-11-10T07:00:00Z", "values": {"rsi": "58.21"}}
                            ],
                        }
                    ],
                }
            ]
        }
    )
