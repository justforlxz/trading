"""风险与敞口端点：只做 HTTP 映射，计算口径在 `app.risk` 里。"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException

from app.api.mapping import decimal_str
from app.api.schemas.risk_exposure import (
    ExposurePositionItem,
    ExposureRuleItem,
    ExposureSummary,
    PositionRiskConfigResponse,
    RiskConfigUpdateRequest,
    RiskExposureResponse,
    SectorExposureItem,
)
from app.risk import (
    RiskExposure,
    SavedRiskConfig,
    exposure_report,
    save_position_risk_config,
)

__all__ = ["risk_exposure_router"]

risk_exposure_router = APIRouter(tags=["risk"])

_CONFIG_FIELDS = ("stop_px", "risk_budget", "warning_threshold_pct")


@risk_exposure_router.get("/risk/exposure", response_model=RiskExposureResponse)
def get_risk_exposure() -> RiskExposureResponse:
    """组合风险与敞口：多空名义价值、行业分布、止损距离与规则结果。"""

    return _exposure(exposure_report())


@risk_exposure_router.put(
    "/positions/{position_ref}/risk-config",
    response_model=PositionRiskConfigResponse,
)
def put_position_risk_config(
    position_ref: str,
    payload: RiskConfigUpdateRequest,
) -> PositionRiskConfigResponse:
    """保存或更新本地止损、风险预算与预警阈值。"""

    changes = {
        name: _optional_decimal(getattr(payload, name))
        for name in _CONFIG_FIELDS
        if name in payload.model_fields_set
    }
    view = save_position_risk_config(position_ref, **changes)
    if view is None:
        raise HTTPException(status_code=404, detail=f"未找到持仓 {position_ref}")
    return _config(view)


def _exposure(view: RiskExposure) -> RiskExposureResponse:
    summary = view.summary
    return RiskExposureResponse(
        as_of=view.as_of,
        status=view.status,  # type: ignore[arg-type]
        summary=ExposureSummary(
            long_notional=decimal_str(summary.long_notional),
            short_notional=decimal_str(summary.short_notional),
            net_notional=decimal_str(summary.net_notional),
            gross_notional=decimal_str(summary.gross_notional),
            margin_usage_pct=_optional_text(summary.margin_usage_pct),
            margin_usage_basis=summary.margin_usage_basis,  # type: ignore[arg-type]
            risk_level=summary.risk_level,
            currency=summary.currency,
        ),
        positions=[
            ExposurePositionItem(
                position_ref=item.position_ref,
                source=item.source,  # type: ignore[arg-type]
                inst_id=item.inst_id,
                display_symbol=item.display_symbol,
                side=item.side,  # type: ignore[arg-type]
                notional=_optional_text(item.notional),
                weight_pct=_optional_text(item.weight_pct),
                mark_px=_optional_text(item.mark_px),
                stop_px=_optional_text(item.stop_px),
                stop_distance_pct=_optional_text(item.stop_distance_pct),
                atr_distance=_optional_text(item.atr_distance),
                lever=_optional_text(item.lever),
                flags=list(item.flags),
            )
            for item in view.positions
        ],
        sectors=[
            SectorExposureItem(
                sector=item.sector,
                notional=decimal_str(item.notional),
                weight_pct=decimal_str(item.weight_pct),
            )
            for item in view.sectors
        ],
        rules=[
            ExposureRuleItem(
                rule_id=item.rule_id,
                level=item.level,
                position_ref=item.position_ref,
                value=_optional_text(item.value),
                threshold=_optional_text(item.threshold),
            )
            for item in view.rules
        ],
    )


def _config(view: SavedRiskConfig) -> PositionRiskConfigResponse:
    return PositionRiskConfigResponse(
        position_ref=view.position_ref,
        stop_px=_optional_text(view.stop_px),
        risk_budget=_optional_text(view.risk_budget),
        warning_threshold_pct=_optional_text(view.warning_threshold_pct),
        source=view.source,
        updated_at=view.updated_at,
    )


def _optional_text(value: Decimal | None) -> str | None:
    return None if value is None else decimal_str(value)


def _optional_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
