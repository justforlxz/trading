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
    "ConditionCatalogResponse",
    "ConditionIndicator",
    "ConditionOutput",
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


class ConditionOutput(BaseModel):
    """条件左值能选到的一个输出列：`name` 写进规则，`title` 给下拉显示。"""

    name: str
    title: str


class ConditionIndicator(BaseModel):
    """回测条件可用的一个指标：`indicator` 就是规则里要写的取值。

    与 `IndicatorDefinition` 分开是因为两者回答的问题不同：那个是「注册表里有
    哪些指标」，这个是「回测条件的左值能用哪几个指标、能选哪一列输出」。参数与
    最小 K 线数由注册表提供，不另写一份。
    """

    indicator: str
    title: str
    summary: str
    outputs: list[ConditionOutput]
    params: list[ParamSpec]
    min_bars: int


class ConditionCatalogResponse(BaseModel):
    items: list[ConditionIndicator]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "indicator": "rsi",
                            "title": "RSI",
                            "summary": "涨跌幅的 Wilder 平滑, 全平序列无方向。",
                            "outputs": [{"name": "rsi", "title": "RSI"}],
                            "params": [
                                {
                                    "name": "period",
                                    "title": "周期",
                                    "kind": "int",
                                    "default": 14,
                                    "minimum": 1,
                                    "maximum": 500,
                                }
                            ],
                            "min_bars": 15,
                        },
                        {
                            "indicator": "macd",
                            "title": "MACD",
                            "summary": "快慢指数均线之差, 及其信号线与柱状差。",
                            "outputs": [
                                {"name": "macd", "title": "DIF"},
                                {"name": "signal", "title": "DEA"},
                                {"name": "hist", "title": "柱"},
                            ],
                            "params": [
                                {
                                    "name": "fast",
                                    "title": "快线周期",
                                    "kind": "int",
                                    "default": 12,
                                    "minimum": 1,
                                    "maximum": 500,
                                },
                                {
                                    "name": "slow",
                                    "title": "慢线周期",
                                    "kind": "int",
                                    "default": 26,
                                    "minimum": 1,
                                    "maximum": 500,
                                },
                                {
                                    "name": "signal",
                                    "title": "信号线周期",
                                    "kind": "int",
                                    "default": 9,
                                    "minimum": 1,
                                    "maximum": 500,
                                },
                            ],
                            "min_bars": 34,
                        },
                    ]
                }
            ]
        }
    )
