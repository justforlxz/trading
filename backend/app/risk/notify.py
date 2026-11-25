"""风控通知设置：五条规则的开关、阈值与通知渠道。

## 为什么阈值不另立一份

阈值与敞口计算用的是同一批键（`settings.risk` 的 `max_leverage` /
`max_single_instrument_weight_pct` / `max_margin_usage_pct`，加上本单新增的
`stop_distance_atr_multiple`）。再存一份「通知用的阈值」就会出现两个真源：界面改的是
通知副本，规则判定读的还是旧值，两边永远对不上。

因此本模块只额外保存两件规则判定不需要的东西——**是否评估**与**通知走哪些渠道**。

## 关掉的规则不参与判定

`load_notify_config().disabled()` 交给 `build_exposure`，被关掉的规则既不产生命中，
也不打持仓标记。这样「关掉杠杆提醒后不再报杠杆过高」是同一份计算结果的自然结果，
而不是在通知发送前再过滤一次——后者会让页面上的命中条与通知内容对不上。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core import ValidationError
from app.risk.exposure import (
    RULE_HIGH_LEVERAGE,
    RULE_MARGIN_USAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
)
from app.settings import DEFAULT_RISK, load_settings, save_settings

__all__ = [
    "CHANNELS",
    "NOTIFY_RULES",
    "NotifyConfig",
    "NotifyRule",
    "load_notify_config",
    "save_notify_config",
]

#: 弹窗里的顺序固定：先看「有没有止损」，再看距离、杠杆、集中度、保证金。
NOTIFY_RULES: tuple[str, ...] = (
    RULE_STOP_MISSING,
    RULE_STOP_DISTANCE,
    RULE_HIGH_LEVERAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_MARGIN_USAGE,
)
#: 通知渠道。`browser` 是内置能力，`telegram` / `webhook` 需要各自配置接收方。
CHANNELS: tuple[str, ...] = ("browser", "telegram", "webhook")

#: 规则 → 阈值在设置文档里的键。`None` 表示这条规则没有阈值。
_THRESHOLD_KEYS: Mapping[str, str | None] = {
    RULE_STOP_MISSING: None,
    RULE_STOP_DISTANCE: "stop_distance_atr_multiple",
    RULE_HIGH_LEVERAGE: "max_leverage",
    RULE_SINGLE_INSTRUMENT_WEIGHT: "max_single_instrument_weight_pct",
    RULE_MARGIN_USAGE: "max_margin_usage_pct",
}


@dataclass(frozen=True, slots=True)
class NotifyRule:
    """一条通知规则：开没开、阈值多少、命中后走哪些渠道。"""

    rule_id: str
    enabled: bool
    channels: tuple[str, ...]
    threshold: Decimal | None


@dataclass(frozen=True, slots=True)
class NotifyConfig:
    """五条规则的完整配置，顺序固定为 `NOTIFY_RULES`。"""

    rules: tuple[NotifyRule, ...]

    def disabled(self) -> frozenset[str]:
        """不参与评估的规则；交给 `build_exposure`。"""

        return frozenset(rule.rule_id for rule in self.rules if not rule.enabled)


def load_notify_config() -> NotifyConfig:
    """读当前配置；旧行缺这一组时按默认值补齐（不需要迁移）。"""

    risk = load_settings().risk
    stored = risk.get("risk_notify")
    stored = stored if isinstance(stored, Mapping) else {}
    rules = []
    for rule_id in NOTIFY_RULES:
        item = stored.get(rule_id)
        item = item if isinstance(item, Mapping) else {}
        default = DEFAULT_RISK["risk_notify"][rule_id]  # type: ignore[index]
        rules.append(
            NotifyRule(
                rule_id=rule_id,
                enabled=bool(item.get("enabled", default["enabled"])),
                channels=_channels(item.get("channels", default["channels"])),
                threshold=_threshold(risk, rule_id),
            )
        )
    return NotifyConfig(tuple(rules))


def save_notify_config(
    rules: Sequence[Mapping[str, object]],
) -> NotifyConfig:
    """保存五条规则；未提交的规则保持原值。

    只影响通知与评估开关：持仓页的权益、名义、保证金占用都来自快照，与这里无关。
    """

    current = load_notify_config()
    by_id = {rule.rule_id: rule for rule in current.rules}
    thresholds: dict[str, object] = {}

    for item in rules:
        rule_id = str(item.get("rule_id") or "")
        if rule_id not in by_id:
            raise ValidationError(f"未知的风控规则 {rule_id or '(空)'}")
        rule = by_id[rule_id]
        enabled = _enabled(item.get("enabled", rule.enabled), rule_id)
        channels = _channels(item.get("channels", rule.channels))
        if enabled and not channels:
            raise ValidationError(f"规则 {rule_id} 开启时必须至少选一个通知渠道")
        by_id[rule_id] = NotifyRule(rule_id, enabled, channels, rule.threshold)
        key = _THRESHOLD_KEYS[rule_id]
        if key is not None and item.get("threshold") is not None:
            thresholds[key] = str(_positive(item.get("threshold"), key))

    return _persist(tuple(by_id[rule_id] for rule_id in NOTIFY_RULES), thresholds)


def _persist(
    rules: tuple[NotifyRule, ...],
    thresholds: Mapping[str, object],
) -> NotifyConfig:
    """把开关与渠道写进 `risk_notify`，阈值写进它们本来所在的键。

    以**当前** `risk` 分组为底再覆盖提交的键：`save_settings` 的 `_merged()` 用默认值
    补齐缺失键，只提交 `risk_notify` 会把 `max_order_notional`、`max_daily_loss`、
    `stop_loss_mandatory` 这些执行风控限额悄悄重置成默认值。
    """

    payload: dict[str, object] = {
        **load_settings().risk,
        "risk_notify": {
            rule.rule_id: {"enabled": rule.enabled, "channels": list(rule.channels)}
            for rule in rules
        },
        **thresholds,
    }
    save_settings(risk=payload)
    return load_notify_config()


def _threshold(risk: Mapping[str, object], rule_id: str) -> Decimal | None:
    key = _THRESHOLD_KEYS[rule_id]
    if key is None:
        return None
    return _positive(risk.get(key), key)


def _positive(value: object, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"{name} 必须是数字") from None
    if not parsed.is_finite() or parsed <= 0:
        raise ValidationError(f"{name} 必须大于 0")
    return parsed


def _enabled(value: object, rule_id: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"规则 {rule_id} 的开关必须是布尔值")
    return value


def _channels(value: object) -> tuple[str, ...]:
    """只保留认识的渠道名，顺序按 `CHANNELS` 归一，避免同一份配置出现两种写法。"""

    if not isinstance(value, (list, tuple)):
        return ()
    wanted = {item for item in value if isinstance(item, str)}
    return tuple(name for name in CHANNELS if name in wanted)
