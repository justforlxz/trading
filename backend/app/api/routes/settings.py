"""设置端点：v6 四类设置的唯一 HTTP 出口。

端点只做请求校验与响应组装；持久化、默认值与凭据应用都在 `app.settings` 里。

- `GET /api/settings` 永不返回 API Key 明文，只返回是否已配置与全掩码；
- `PATCH /api/settings` 按分组部分更新，成本与回测默认值不再经 HTTP 暴露；
- 数据源的最后同步时间与失败次数来自 `data_sync_jobs`，不由前端推算。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import (
    DataSourceSettings,
    DisplaySettings,
    ExecutionSettings,
    RiskDefaults,
    SecretSettings,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.market import sync_summary
from app.settings import SettingsRecord, load_settings, save_settings

__all__ = ["settings_router"]

settings_router = APIRouter(tags=["settings"])


@settings_router.get("/settings", response_model=SettingsResponse)
def get_settings_document() -> SettingsResponse:
    """当前设置：显示偏好、风险默认值、执行开关、数据源与密钥状态。"""

    return _response(load_settings())


@settings_router.patch("/settings", response_model=SettingsResponse)
def patch_settings_document(payload: SettingsUpdateRequest) -> SettingsResponse:
    """按分组部分更新；未提交的分组保持原值。"""

    record = save_settings(
        display=None if payload.display is None else payload.display.model_dump(mode="json"),
        risk_defaults=None
        if payload.risk_defaults is None
        else payload.risk_defaults.model_dump(mode="json"),
        execution=None if payload.execution is None else payload.execution.model_dump(mode="json"),
        data_sources=None
        if payload.data_sources is None
        else payload.data_sources.model_dump(exclude_unset=True),
        api_key=_api_key(payload),
    )
    return _response(record)


def _api_key(payload: SettingsUpdateRequest) -> str | None:
    if payload.exchange is None or payload.exchange.api_key is None:
        return None
    return payload.exchange.api_key.get_secret_value()


def _response(record: SettingsRecord) -> SettingsResponse:
    provider = record.data_sources.get("provider")
    last_sync_at = None
    failure_count = 0
    if isinstance(provider, str) and provider:
        last_sync_at, failure_count = sync_summary(provider)
    return SettingsResponse(
        display=DisplaySettings(**record.display),
        risk_defaults=RiskDefaults(**record.risk_defaults),
        execution=ExecutionSettings(**record.execution),
        data_sources=DataSourceSettings(
            provider=provider if isinstance(provider, str) else None,
            subscribed_instruments=list(record.data_sources.get("subscribed_instruments", [])),
            last_sync_at=last_sync_at,
            failure_count=failure_count,
        ),
        secrets=SecretSettings(
            okx_api_key_masked=record.api_key_masked,
            okx_configured=record.api_configured,
            okx_permission="unknown" if record.api_configured else None,
        ),
        updated_at=record.updated_at,
    )
