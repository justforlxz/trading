"""指标域端点：指标目录与按标的/周期的指标序列。

目录直接由注册表生成，不另维护一份清单；序列只读已收盘 K 线，参数默认值补全与
范围校验都在 `app.indicators` 里完成，这一层只做入参形状校验与响应组装。

`params` 是请求侧的可选通道：冻结的请求形状里没有传递指标参数的位置，缺省时指标
只能按注册表默认值计算，因此补一个 JSON 对象字符串按名覆盖单个指标的参数。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.mapping import decimal_str
from app.api.schemas import (
    IndicatorCatalogResponse,
    IndicatorPoint,
    IndicatorSeries,
    IndicatorSeriesResponse,
)
from app.api.schemas import IndicatorDefinition as IndicatorDefinitionPayload
from app.api.schemas.common import Bar, ParamSpec, ParamValue
from app.core import Bar as CandleBar
from app.core import ValidationError
from app.indicators import (
    IndicatorDefinition,
    Param,
    Series,
    compute,
    list_definitions,
)
from app.instrument import list_instruments
from app.market import load_candles

__all__ = ["indicators_router"]

indicators_router = APIRouter(tags=["indicators"])

# 参数不合法（越界、未知名字、不是合法 JSON）一律按「请求可以被修正后重试」处理，
# 与冻结契约里查询参数校验错误同为 422。
_PARAM_ERROR = 422

# 契约里的 DecimalString 只保证 12 位小数；比值类指标（如 RSI 的 100/1.5）会算出
# 无限小数，必须在出接口前按契约精度量化，否则响应模型校验直接 500。
_VALUE_QUANTUM = Decimal("1e-12")


@indicators_router.get("/indicators", response_model=IndicatorCatalogResponse)
def list_indicators() -> IndicatorCatalogResponse:
    """指标目录：每条声明都来自注册表，形状与 `schemas/indicators.py` 一一对应。"""

    return IndicatorCatalogResponse(items=[_definition(row) for row in list_definitions()])


@indicators_router.get("/indicators/series", response_model=IndicatorSeriesResponse)
def get_indicator_series(
    inst_id: str = Query(...),
    bar: Bar = Query(...),
    names: str = Query(..., description="逗号分隔的指标名 (如 rsi,sma)"),
    limit: int = Query(200, ge=1, le=1000),
    params: str | None = Query(
        None,
        description='可选参数通道, JSON 对象形如 {"rsi":{"period":14},"sma":{"period":20}}',
    ),
) -> IndicatorSeriesResponse:
    """按标的与周期算一组指标；参数缺省用注册表默认值，缺数据时序列为空。"""

    instrument = next((row for row in list_instruments() if row.symbol == inst_id), None)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"未找到标的 {inst_id}")

    requested = _parse_names(names)
    overrides = _parse_params(params, requested)

    # `candles` 只存已收盘 K 线；这里仍按 `confirm` 过滤，守住「未收盘数据不得
    # 冒充已确认值」的端口约定，而不依赖存储层的写入约束。
    bars = [candle for candle in load_candles(instrument.symbol, bar) if candle.confirm][-limit:]

    return IndicatorSeriesResponse(
        inst_id=instrument.symbol,
        inst_type=instrument.inst_type,
        bar=bar,
        series=[_series(name, bars, overrides.get(name)) for name in requested],
    )


def _definition(row: IndicatorDefinition) -> IndicatorDefinitionPayload:
    """域声明 → 契约声明：`min_length` 在接口层叫 `min_bars`，其余字段同名。"""

    return IndicatorDefinitionPayload(
        name=row.name,
        title=row.title,
        summary=row.summary,
        params=[_param_spec(param) for param in row.params],
        outputs=list(row.outputs),
        min_bars=row.min_length,
    )


def _param_spec(param: Param) -> ParamSpec:
    return ParamSpec(
        name=param.name,
        title=param.title,
        kind=param.kind,
        default=param.default,
        minimum=param.minimum,
        maximum=param.maximum,
    )


def _series(
    name: str, bars: Sequence[CandleBar], overrides: dict[str, ParamValue] | None
) -> IndicatorSeries:
    """单个指标的序列；名字未登记或参数越界都由注册表抛 `ValidationError`。"""

    try:
        result = compute(name, bars, overrides)
    except ValidationError as exc:
        raise HTTPException(status_code=_PARAM_ERROR, detail=str(exc)) from None
    return _series_payload(result)


def _value_str(value: Decimal) -> str:
    """按契约精度量化后再序列化，避免无限小数破坏 DecimalString 形状。"""

    return decimal_str(value.quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP))


def _series_payload(result: Series) -> IndicatorSeries:
    return IndicatorSeries(
        name=result.name,
        params=dict(result.params),
        points=[
            IndicatorPoint(
                time=point.time,
                values={
                    column: None if value is None else _value_str(value)
                    for column, value in point.values.items()
                },
            )
            for point in result.points
        ],
    )


def _parse_names(raw: str) -> list[str]:
    """逗号分隔的指标名，去掉空白与重复；一个都没有按参数不合法处理。"""

    names = list(dict.fromkeys(name.strip() for name in raw.split(",") if name.strip()))
    if not names:
        raise HTTPException(status_code=_PARAM_ERROR, detail="names 至少要有一个指标名")
    return names


def _parse_params(raw: str | None, requested: list[str]) -> dict[str, dict[str, ParamValue]]:
    """把 `params` 解成「指标名 → 参数表」；结构与键的合法性在这里检查。

    参数值本身的类型与范围交给注册表校验（`compute` 内统一做），避免在接口层
    再维护一份与指标声明平行的规则。
    """

    if raw is None or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=_PARAM_ERROR, detail=f"params 不是合法 JSON:{exc.msg}"
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=_PARAM_ERROR, detail="params 必须是 JSON 对象")

    unknown = sorted(set(payload) - set(requested))
    if unknown:
        raise HTTPException(
            status_code=_PARAM_ERROR, detail=f"params 含未请求的指标:{', '.join(unknown)}"
        )
    for name, value in payload.items():
        if not isinstance(value, dict):
            raise HTTPException(status_code=_PARAM_ERROR, detail=f"{name} 的参数必须是 JSON 对象")
    return payload
