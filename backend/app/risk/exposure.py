"""持仓风险与敞口的纯计算。

输入是一批已经归一化的持仓、标的规格、行情与本地止损配置；输出是可直接序列化的
风险视图。这里不读库、不联网、不看时钟，因此同一条持仓与同一组阈值重复计算必然
得到同一个结果。

口径固定如下：

- 名义价值：交易所永续 `size * mark_px * ctVal * ctMult`，现货与手动持仓按基础数量
  `size * mark_px`；缺标的规格或价格时留空，不用 0 或相似标的价格顶替。
- 单标的占比：同一 `display_symbol` 的持仓名义价值合计 / 组合总名义价值。现货与
  永续是同一标的的两种形态，集中度必须合并看。
- 行业敞口：按 `instrument.sector` 汇总，未分类统一落到 `unclassified`。
- 止损距离：多头 `(mark - stop) / mark`，空头 `(stop - mark) / mark`；负值表示价格
  已经穿过止损。`stop_distance_pct` 是百分比，`atr_distance` 是价格距离除以 ATR。
- 风险等级：`critical` 规则映射为 `high`，只有 `warning` 规则映射为 `medium`，
  没有触发规则才是 `low`。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.instrument import trading_rules

__all__ = [
    "ATR_PERIOD",
    "RULE_HIGH_LEVERAGE",
    "RULE_MARGIN_USAGE",
    "RULE_SINGLE_INSTRUMENT_WEIGHT",
    "RULE_STOP_DISTANCE",
    "RULE_STOP_MISSING",
    "ExposurePosition",
    "ExposureRule",
    "ExposureSummary",
    "PositionRiskInput",
    "RiskExposure",
    "RiskThresholds",
    "SectorExposure",
    "build_exposure",
    "notional_value",
]

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
ATR_PERIOD = 14
UNCLASSIFIED = "unclassified"

RULE_STOP_MISSING = "stop_missing"
RULE_STOP_DISTANCE = "stop_distance"
RULE_HIGH_LEVERAGE = "high_leverage"
RULE_SINGLE_INSTRUMENT_WEIGHT = "single_instrument_weight"
RULE_MARGIN_USAGE = "margin_usage"

_FLAG_NO_MARKET_DATA = "no_market_data"
_FLAG_ATR_UNAVAILABLE = "atr_unavailable"

RiskLevel = Literal["low", "medium", "high"]
RuleLevel = Literal["warning", "critical"]


@dataclass(frozen=True, slots=True)
class RiskThresholds:
    """风险规则阈值；全部来自设置，不在计算里写死。"""

    max_leverage: Decimal
    max_single_instrument_weight_pct: Decimal
    max_margin_usage_pct: Decimal


@dataclass(frozen=True, slots=True)
class PositionRiskInput:
    """一条待计算的持仓。`inst_type` 为空表示标的表里找不到这条标的。"""

    position_ref: str
    source: Literal["exchange", "manual"]
    inst_id: str
    display_symbol: str
    side: Literal["long", "short"]
    size: Decimal
    inst_type: str | None
    mark_px: Decimal | None
    stop_px: Decimal | None
    atr: Decimal | None
    lever: Decimal | None
    sector: str | None
    ct_val: Decimal | None
    ct_mult: Decimal | None


@dataclass(frozen=True, slots=True)
class ExposurePosition:
    position_ref: str
    source: str
    inst_id: str
    display_symbol: str
    side: str
    notional: Decimal | None
    weight_pct: Decimal | None
    mark_px: Decimal | None
    stop_px: Decimal | None
    stop_distance_pct: Decimal | None
    atr_distance: Decimal | None
    lever: Decimal | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectorExposure:
    sector: str
    notional: Decimal
    weight_pct: Decimal


@dataclass(frozen=True, slots=True)
class ExposureRule:
    rule_id: str
    level: RuleLevel
    position_ref: str | None
    value: Decimal | None
    threshold: Decimal | None


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    long_notional: Decimal
    short_notional: Decimal
    net_notional: Decimal
    gross_notional: Decimal
    margin_usage_pct: Decimal | None
    margin_usage_basis: str | None
    risk_level: RiskLevel
    currency: str


@dataclass(frozen=True, slots=True)
class RiskExposure:
    as_of: datetime
    status: str
    summary: ExposureSummary
    positions: tuple[ExposurePosition, ...]
    sectors: tuple[SectorExposure, ...]
    rules: tuple[ExposureRule, ...]


def notional_value(position: PositionRiskInput) -> Decimal | None:
    """按标的类别与合约规格计算名义价值；缺一项必需输入就返回 `None`。"""

    if position.inst_type is None or position.mark_px is None:
        return None
    size = abs(position.size)
    # 手动持仓账本按基础数量记账（`price * quantity`），不是合约张数；再乘
    # `ctVal * ctMult` 会与 `/api/manual-positions` 的市值口径分叉。
    if position.source == "manual":
        return size * position.mark_px
    if not trading_rules(position.inst_type).has_margin:
        return size * position.mark_px
    if position.ct_val is None or position.ct_mult is None:
        return None
    return size * position.mark_px * position.ct_val * position.ct_mult


def _price_distance(position: PositionRiskInput) -> Decimal | None:
    if position.mark_px is None or position.stop_px is None:
        return None
    if position.mark_px == ZERO:
        return None
    if position.side == "long":
        return position.mark_px - position.stop_px
    return position.stop_px - position.mark_px


def _stop_distance_pct(position: PositionRiskInput) -> Decimal | None:
    distance = _price_distance(position)
    if distance is None or position.mark_px is None:
        return None
    return distance / position.mark_px * HUNDRED


def _atr_distance(position: PositionRiskInput) -> Decimal | None:
    distance = _price_distance(position)
    if distance is None or position.atr is None or position.atr <= ZERO:
        return None
    return distance / position.atr


def _ratio_pct(part: Decimal, total: Decimal) -> Decimal | None:
    if total <= ZERO:
        return None
    return part / total * HUNDRED


def build_exposure(
    positions: tuple[PositionRiskInput, ...],
    *,
    as_of: datetime,
    currency: str,
    thresholds: RiskThresholds,
    margin_usage_pct: Decimal | None = None,
    margin_usage_basis: str | None = None,
) -> RiskExposure:
    """把持仓压成持仓级、行业级、组合级三层风险视图。"""

    notionals = {position.position_ref: notional_value(position) for position in positions}
    long_notional = sum(
        (
            value
            for position in positions
            if (value := notionals[position.position_ref]) is not None and position.side == "long"
        ),
        ZERO,
    )
    short_notional = sum(
        (
            value
            for position in positions
            if (value := notionals[position.position_ref]) is not None and position.side == "short"
        ),
        ZERO,
    )
    gross_notional = long_notional + short_notional

    symbol_notional: dict[str, Decimal] = defaultdict(lambda: ZERO)
    symbol_refs: dict[str, list[str]] = defaultdict(list)
    for position in positions:
        value = notionals[position.position_ref]
        if value is None:
            continue
        symbol_notional[position.display_symbol] += value
        symbol_refs[position.display_symbol].append(position.position_ref)

    rules: list[ExposureRule] = []
    flags: dict[str, list[str]] = {position.position_ref: [] for position in positions}

    def flag(position_ref: str, name: str) -> None:
        if name not in flags[position_ref]:
            flags[position_ref].append(name)

    for position in positions:
        value = notionals[position.position_ref]
        if value is None:
            flag(position.position_ref, _FLAG_NO_MARKET_DATA)

        if position.stop_px is None:
            rules.append(
                ExposureRule(
                    rule_id=RULE_STOP_MISSING,
                    level="warning",
                    position_ref=position.position_ref,
                    value=None,
                    threshold=None,
                )
            )
            flag(position.position_ref, RULE_STOP_MISSING)
        else:
            distance = _price_distance(position)
            atr_distance = _atr_distance(position)
            if atr_distance is not None and atr_distance < ONE:
                rules.append(
                    ExposureRule(
                        rule_id=RULE_STOP_DISTANCE,
                        level="critical" if distance is not None and distance < ZERO else "warning",
                        position_ref=position.position_ref,
                        value=atr_distance,
                        threshold=ONE,
                    )
                )
                flag(position.position_ref, RULE_STOP_DISTANCE)
            elif atr_distance is None and distance is not None and distance < ZERO:
                rules.append(
                    ExposureRule(
                        rule_id=RULE_STOP_DISTANCE,
                        level="critical",
                        position_ref=position.position_ref,
                        value=_stop_distance_pct(position),
                        threshold=ZERO,
                    )
                )
                flag(position.position_ref, RULE_STOP_DISTANCE)
            if atr_distance is None and position.mark_px is not None:
                flag(position.position_ref, _FLAG_ATR_UNAVAILABLE)

        if position.lever is not None and position.lever > thresholds.max_leverage:
            rules.append(
                ExposureRule(
                    rule_id=RULE_HIGH_LEVERAGE,
                    level="warning",
                    position_ref=position.position_ref,
                    value=position.lever,
                    threshold=thresholds.max_leverage,
                )
            )
            flag(position.position_ref, RULE_HIGH_LEVERAGE)

    for symbol, value in symbol_notional.items():
        weight = _ratio_pct(value, gross_notional)
        if weight is None or weight <= thresholds.max_single_instrument_weight_pct:
            continue
        refs = sorted(symbol_refs[symbol])
        rules.append(
            ExposureRule(
                rule_id=RULE_SINGLE_INSTRUMENT_WEIGHT,
                level="warning",
                position_ref=refs[0],
                value=weight,
                threshold=thresholds.max_single_instrument_weight_pct,
            )
        )
        for ref in refs:
            flag(ref, RULE_SINGLE_INSTRUMENT_WEIGHT)

    if margin_usage_pct is not None and margin_usage_pct > thresholds.max_margin_usage_pct:
        rules.append(
            ExposureRule(
                rule_id=RULE_MARGIN_USAGE,
                level="warning",
                position_ref=None,
                value=margin_usage_pct,
                threshold=thresholds.max_margin_usage_pct,
            )
        )

    levels = {rule.level for rule in rules}
    risk_level: RiskLevel = "low"
    if "critical" in levels:
        risk_level = "high"
    elif "warning" in levels:
        risk_level = "medium"

    exposures = tuple(
        ExposurePosition(
            position_ref=position.position_ref,
            source=position.source,
            inst_id=position.inst_id,
            display_symbol=position.display_symbol,
            side=position.side,
            notional=notionals[position.position_ref],
            weight_pct=_ratio_pct(notionals[position.position_ref] or ZERO, gross_notional)
            if notionals[position.position_ref] is not None
            else None,
            mark_px=position.mark_px,
            stop_px=position.stop_px,
            stop_distance_pct=_stop_distance_pct(position),
            atr_distance=_atr_distance(position),
            lever=position.lever,
            flags=tuple(flags[position.position_ref]),
        )
        for position in positions
    )

    sector_notional: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for position in positions:
        value = notionals[position.position_ref]
        if value is None:
            continue
        sector = position.sector or UNCLASSIFIED
        sector_notional[sector] += value

    sectors = tuple(
        SectorExposure(
            sector=sector,
            notional=value,
            weight_pct=_ratio_pct(value, gross_notional) or ZERO,
        )
        for sector, value in sorted(sector_notional.items())
    )

    summary = ExposureSummary(
        long_notional=long_notional,
        short_notional=short_notional,
        net_notional=long_notional - short_notional,
        gross_notional=gross_notional,
        margin_usage_pct=margin_usage_pct,
        margin_usage_basis=margin_usage_basis,
        risk_level=risk_level,
        currency=currency,
    )
    return RiskExposure(
        as_of=as_of,
        status="ok" if positions else "empty",
        summary=summary,
        positions=exposures,
        sectors=sectors,
        rules=tuple(rules),
    )
