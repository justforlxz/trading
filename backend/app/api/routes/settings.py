"""设置端点：凭证状态与执行模式的唯一 HTTP 出口。

端点只做请求校验与响应组装；持久化、默认值与凭据应用都在 `app.settings` 里。

- `GET /api/settings` 永不返回 API Key 明文，只返回是否已配置与全掩码。
- `PUT /api/settings` 按分组部分更新；切到实盘必须带 `acknowledge_risk=true`，
  否则返回 409 且不写入任何分组。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    BacktestSettings,
    CostSettings,
    DataSettings,
    ExchangeSettings,
    ExecutionSettings,
    RiskSettings,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.settings import SettingsRecord, load_settings, save_settings

__all__ = ["settings_router"]

settings_router = APIRouter(tags=["settings"])


@settings_router.get("/settings", response_model=SettingsResponse)
def get_settings_document() -> SettingsResponse:
    """当前设置：分组配置、凭证状态与执行模式。"""

    return _response(load_settings())


@settings_router.put("/settings", response_model=SettingsResponse)
def update_settings_document(payload: SettingsUpdateRequest) -> SettingsResponse:
    """按分组部分更新；未提交的分组保持原值。"""

    current = load_settings()
    switching_to_live = (
        payload.execution is not None
        and payload.execution.mode == "live"
        and current.execution["mode"] != "live"
    )
    if switching_to_live and not payload.acknowledge_risk:
        raise HTTPException(
            status_code=409,
            detail="切换到实盘必须携带 acknowledge_risk=true",
        )

    record = save_settings(
        execution=_group(payload.execution),
        risk=_group(payload.risk),
        costs=_group(payload.costs),
        backtest=_group(payload.backtest),
        data=_group(payload.data),
        api_key=_api_key(payload),
    )
    return _response(record)


def _group(
    value: ExecutionSettings | RiskSettings | CostSettings | BacktestSettings | DataSettings | None,
) -> dict | None:
    return None if value is None else value.model_dump(mode="json")


def _api_key(payload: SettingsUpdateRequest) -> str | None:
    if payload.exchange is None or payload.exchange.api_key is None:
        return None
    return payload.exchange.api_key.get_secret_value()


def _response(record: SettingsRecord) -> SettingsResponse:
    return SettingsResponse(
        execution=ExecutionSettings(**record.execution),
        risk=RiskSettings(**record.risk),
        costs=CostSettings(**record.costs),
        backtest=BacktestSettings(**record.backtest),
        exchange=ExchangeSettings(
            demo_trading=record.demo_trading,
            api_configured=record.api_configured,
            api_key_masked=record.api_key_masked,
        ),
        data=DataSettings(**record.data),
        updated_at=record.updated_at,
    )
