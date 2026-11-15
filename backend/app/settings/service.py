"""设置域：读取、写入并应用唯一的一份配置文档。

## 凭据

`okx_api_key` 只写不读：`SettingsRecord` 里的 `api_key` 只供进程内应用使用，
HTTP 层拿到的只有 `api_configured` 与全掩码字符串。Secret 与 Passphrase 不在本域
保存，仍由环境变量注入。

## 分组

v6 只经 HTTP 暴露四类：显示偏好、风险默认值、自动执行开关与数据源状态，另有只读的
密钥状态。`risk`（执行风控限额）、`costs` 与 `backtest` 仍是服务端内部参数，保留在
设置文档里，但不进入 `GET` / `PATCH /api/settings` 的响应与请求。

## 生效方式

写入后立即把 API Key 应用到进程配置；进程启动时再由装配根调用一次
`apply_saved_settings()`，因此重启后仍然生效。执行开关与其余分组持久化在本表，
由各自的使用方读取，本域不替它们做业务判断。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import Clock, InvariantViolation, SystemClock
from app.db import session_scope
from app.settings.model import SettingsRow

__all__ = [
    "DEFAULT_BACKTEST",
    "DEFAULT_COSTS",
    "DEFAULT_DATA_SOURCES",
    "DEFAULT_DISPLAY",
    "DEFAULT_EXECUTION",
    "DEFAULT_RISK",
    "DEFAULT_RISK_DEFAULTS",
    "MASKED_API_KEY",
    "SettingsRecord",
    "apply_saved_settings",
    "load_settings",
    "save_settings",
]

SETTINGS_ID = 1
MASKED_API_KEY = "********"

DEFAULT_EXECUTION: dict[str, Any] = {"auto_trading_enabled": False}
DEFAULT_RISK: dict[str, Any] = {
    "max_order_notional": "1000",
    "max_position_notional": "3000",
    "max_total_notional": "10000",
    "max_positions": 5,
    "max_leverage": "3",
    # B3 风险与敞口阈值：单标的占组合总名义价值的上限，以及保证金使用率上限。
    "max_single_instrument_weight_pct": "35",
    "max_margin_usage_pct": "70",
    "max_daily_loss": "300",
    "liquidation_buffer_pct": "10",
    "stop_loss_mandatory": True,
}
DEFAULT_COSTS: dict[str, Any] = {
    "maker_fee_bps": "2",
    "taker_fee_bps": "5",
    "slippage_bps": "3",
    "spread_bps": "2",
}
DEFAULT_BACKTEST: dict[str, Any] = {
    "funding_enabled": True,
    "default_initial_capital": "10000",
    "default_bar": "1h",
}
DEFAULT_DISPLAY: dict[str, Any] = {
    "color_scheme": "system",
    "default_bar": "1d",
    "price_precision": 2,
    "home_layout": "cockpit",
}
DEFAULT_RISK_DEFAULTS: dict[str, Any] = {
    "default_leverage": "3",
    "risk_budget_per_trade": "100",
    "warning_threshold": "80",
    "stop_rule": "fixed_pct",
}
DEFAULT_DATA_SOURCES: dict[str, Any] = {
    "provider": None,
    "subscribed_instruments": [],
}


@dataclass(frozen=True, slots=True)
class SettingsRecord:
    """一份设置文档的只读视图。

    `api_key` 是明文，只允许进程内使用；HTTP 层只能读 `api_key_masked` 与
    `api_configured`。
    """

    execution: Mapping[str, Any]
    risk: Mapping[str, Any]
    costs: Mapping[str, Any]
    backtest: Mapping[str, Any]
    display: Mapping[str, Any]
    risk_defaults: Mapping[str, Any]
    data_sources: Mapping[str, Any]
    api_configured: bool
    api_key_masked: str | None
    api_key: str | None
    updated_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "execution",
            "risk",
            "costs",
            "backtest",
            "display",
            "risk_defaults",
            "data_sources",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        if self.updated_at.tzinfo is None:
            raise InvariantViolation("设置文档的 updated_at 必须带时区")


def _parse(name: str, value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise InvariantViolation(f"设置分组 {name} 不是 JSON 对象")
    return parsed


def _dump(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _merged(defaults: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    merged.update({key: item for key, item in value.items() if key in defaults})
    return merged


def _execution_view(value: Mapping[str, Any]) -> dict[str, Any]:
    """只保留 v6 仍展示的自动执行开关；旧行里的模式与紧急停止直接忽略。"""

    enabled = value.get("auto_trading_enabled", False)
    return {"auto_trading_enabled": enabled if isinstance(enabled, bool) else False}


def _data_sources_view(value: Mapping[str, Any]) -> dict[str, Any]:
    provider = value.get("provider")
    if provider is not None and not isinstance(provider, str):
        provider = None
    subscribed = value.get("subscribed_instruments", [])
    if not isinstance(subscribed, list):
        subscribed = []
    return {
        "provider": provider.strip() if isinstance(provider, str) and provider.strip() else None,
        "subscribed_instruments": [
            item for item in subscribed if isinstance(item, str) and item.strip()
        ],
    }


def _default_row(moment: datetime) -> SettingsRow:
    return SettingsRow(
        id=SETTINGS_ID,
        execution=_dump(DEFAULT_EXECUTION),
        risk=_dump(DEFAULT_RISK),
        costs=_dump(DEFAULT_COSTS),
        backtest=_dump(DEFAULT_BACKTEST),
        display=_dump(DEFAULT_DISPLAY),
        risk_defaults=_dump(DEFAULT_RISK_DEFAULTS),
        data_sources=_dump(DEFAULT_DATA_SOURCES),
        okx_api_key=None,
        updated_at=moment,
    )


def _record(row: SettingsRow) -> SettingsRecord:
    runtime = get_settings()
    api_key = row.okx_api_key or runtime.okx_api_key or None
    return SettingsRecord(
        execution=_execution_view(_parse("execution", row.execution)),
        risk=_merged(DEFAULT_RISK, _parse("risk", row.risk)),
        costs=_merged(DEFAULT_COSTS, _parse("costs", row.costs)),
        backtest=_merged(DEFAULT_BACKTEST, _parse("backtest", row.backtest)),
        display=_merged(DEFAULT_DISPLAY, _parse("display", row.display)),
        risk_defaults=_merged(DEFAULT_RISK_DEFAULTS, _parse("risk_defaults", row.risk_defaults)),
        data_sources=_data_sources_view(_parse("data_sources", row.data_sources)),
        api_configured=bool(api_key),
        api_key_masked=MASKED_API_KEY if api_key else None,
        api_key=api_key,
        updated_at=row.updated_at,
    )


def _row_for_update(session: Session, now: datetime) -> SettingsRow:
    row = session.get(SettingsRow, SETTINGS_ID)
    if row is None:
        row = _default_row(now)
        session.add(row)
    return row


def load_settings(*, clock: Clock | None = None) -> SettingsRecord:
    """读取设置；首次读取时写入默认文档，保证 `updated_at` 在后续读取中稳定。"""

    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        row = _row_for_update(session, moment)
        session.flush()
        return _record(row)


def save_settings(
    *,
    execution: Mapping[str, Any] | None = None,
    risk: Mapping[str, Any] | None = None,
    costs: Mapping[str, Any] | None = None,
    backtest: Mapping[str, Any] | None = None,
    display: Mapping[str, Any] | None = None,
    risk_defaults: Mapping[str, Any] | None = None,
    data_sources: Mapping[str, Any] | None = None,
    subscribed_instruments: Sequence[str] | None = None,
    api_key: str | None = None,
    clock: Clock | None = None,
) -> SettingsRecord:
    """按分组部分更新设置；未提交的分组保持原值。

    `api_key` 只在非空时覆盖；空字符串表示「本次不修改」，不会把已有密钥清空。
    `subscribed_instruments` 单独给出时只替换订阅清单，不动 Provider。
    """

    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        row = _row_for_update(session, moment)
        if execution is not None:
            row.execution = _dump(_execution_view(execution))
        if risk is not None:
            row.risk = _dump(_merged(DEFAULT_RISK, risk))
        if costs is not None:
            row.costs = _dump(_merged(DEFAULT_COSTS, costs))
        if backtest is not None:
            row.backtest = _dump(_merged(DEFAULT_BACKTEST, backtest))
        if display is not None:
            row.display = _dump(_merged(DEFAULT_DISPLAY, display))
        if risk_defaults is not None:
            row.risk_defaults = _dump(_merged(DEFAULT_RISK_DEFAULTS, risk_defaults))
        if data_sources is not None:
            row.data_sources = _dump(
                _data_sources_view({**_parse("data_sources", row.data_sources), **data_sources})
            )
        if subscribed_instruments is not None:
            current = _data_sources_view(_parse("data_sources", row.data_sources))
            current["subscribed_instruments"] = [
                item for item in subscribed_instruments if isinstance(item, str) and item.strip()
            ]
            row.data_sources = _dump(current)
        if api_key is not None and api_key.strip():
            row.okx_api_key = api_key.strip()
        row.updated_at = moment
        session.flush()
        record = _record(row)

    if record.api_key:
        get_settings().okx_api_key = record.api_key
    return record


def apply_saved_settings() -> None:
    """把已保存的 API Key 应用到进程配置；没有保存过时保留环境变量里的值。"""

    record = load_settings()
    if record.api_key:
        get_settings().okx_api_key = record.api_key
