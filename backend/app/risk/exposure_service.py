"""持仓风险视图的编排：读快照、手动持仓、本地配置与日线，交给纯函数计算。

本层只做 IO 与事务边界。交易所持仓取最近一次账户快照，手动持仓只取仍在持仓状态
的记录；行情与 ATR 只从已落库、已收盘的日线读取，没有行情时留空。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import Bar, Clock, SystemClock, UnprocessableEntity
from app.db import session_scope
from app.indicators import compute
from app.instrument import Instrument, get_instruments, okx_source
from app.market import latest_candles_by_source, load_candles_by_source
from app.positions import (
    STOP_CONFIRMED,
    AccountView,
    ExchangePositionsView,
    ExchangePositionView,
    ManualPositionView,
    PositionRiskConfigRow,
    account_summary,
    exchange_positions,
    list_open_manual_positions,
)
from app.risk.exposure import (
    ATR_PERIOD,
    PositionRiskInput,
    RiskExposure,
    RiskThresholds,
    build_exposure,
)
from app.risk.notify import load_notify_config
from app.settings import load_settings

__all__ = [
    "SavedRiskConfig",
    "exposure_from_positions",
    "exposure_report",
    "save_position_risk_config",
]

ZERO = Decimal(0)
HUNDRED = Decimal(100)
CONFIG_SOURCE = "local"
DAILY_BAR = "1d"

_UNSET = object()


@dataclass(frozen=True, slots=True)
class SavedRiskConfig:
    position_ref: str
    stop_px: Decimal | None
    risk_budget: Decimal | None
    warning_threshold_pct: Decimal | None
    source: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class _InstrumentRiskData:
    inst_type: str | None
    display_symbol: str
    sector: str | None
    ct_val: Decimal | None
    ct_mult: Decimal | None
    latest_price: Decimal | None
    atr: Decimal | None


def exposure_report(*, clock: Clock | None = None) -> RiskExposure:
    """当前组合的风险与敞口；没有持仓时返回空视图，不编造数值。

    自己读一次账户、交易所持仓与手动持仓。首页一次请求里这三份事实由调用方读完
    后经 `exposure_from_positions` 传进来，风险和持仓两个模块共用同一份。
    """

    return exposure_from_positions(
        # 名义合计是保证金占用率的分母来源，这里必须带上，否则占用率恒为 `None`。
        account_summary(),
        exchange_positions(),
        list_open_manual_positions(),
        clock=clock,
    )


def exposure_from_positions(
    account: AccountView,
    exchange: ExchangePositionsView,
    manual: Sequence[ManualPositionView],
    *,
    clock: Clock | None = None,
) -> RiskExposure:
    """用已读到的持仓事实算敞口：读什么由 `exposure_report` 决定，本函数只算。"""

    exchange_refs = {
        f"exchange:{account.account_id}:{item.pos_id}": item for item in exchange.items
    }
    manual_refs = {f"manual:{item.id}": item for item in manual}
    configs = _load_configs((*exchange_refs, *manual_refs))

    symbols = {item.inst_id for item in exchange.items} | {item.inst_id for item in manual}
    instrument_data = _instrument_data(symbols)

    positions = [
        _exchange_input(ref, item, configs.get(ref), instrument_data)
        for ref, item in exchange_refs.items()
    ]
    positions.extend(
        _manual_input(ref, item, configs.get(ref), instrument_data)
        for ref, item in manual_refs.items()
    )

    usage, basis = _margin_usage(account)
    return build_exposure(
        tuple(positions),
        as_of=account.captured_at or (clock or SystemClock()).now(),
        currency=account.currency,
        thresholds=_thresholds(),
        margin_usage_pct=usage,
        margin_usage_basis=basis,
        disabled_rules=load_notify_config().disabled(),
    )


def save_position_risk_config(
    position_ref: str,
    *,
    stop_px: Decimal | object | None = _UNSET,
    risk_budget: Decimal | object | None = _UNSET,
    warning_threshold_pct: Decimal | object | None = _UNSET,
    clock: Clock | None = None,
) -> SavedRiskConfig | None:
    """保存或更新一条持仓的本地风险配置；持仓引用不存在时返回 `None`。"""

    ref = position_ref.strip()
    if not ref or ref not in _known_position_refs():
        return None

    _require_positive(stop_px, "止损价")
    _require_positive(risk_budget, "风险预算")
    _require_threshold(warning_threshold_pct)
    moment = (clock or SystemClock()).now()

    with session_scope() as session:
        values: dict[str, object] = {
            "id": str(uuid4()),
            "position_ref": ref,
            "stop_px": None,
            "risk_budget": None,
            "warning_threshold_pct": None,
            "source": CONFIG_SOURCE,
            "updated_at": moment,
        }
        updates: dict[str, object] = {"updated_at": moment}
        if stop_px is not _UNSET:
            values["stop_px"] = stop_px
            updates["stop_px"] = stop_px
        if risk_budget is not _UNSET:
            values["risk_budget"] = risk_budget
            updates["risk_budget"] = risk_budget
        if warning_threshold_pct is not _UNSET:
            values["warning_threshold_pct"] = warning_threshold_pct
            updates["warning_threshold_pct"] = warning_threshold_pct
        statement = (
            postgresql_insert(PositionRiskConfigRow)
            .values(**values)
            .on_conflict_do_update(index_elements=["position_ref"], set_=updates)
            .returning(PositionRiskConfigRow)
        )
        return _config_view(session.scalars(statement).one())


def _known_position_refs() -> set[str]:
    account = account_summary(include_position_notional=False)
    exchange = exchange_positions()
    refs = {f"exchange:{account.account_id}:{item.pos_id}" for item in exchange.items}
    refs.update(f"manual:{item.id}" for item in list_open_manual_positions())
    return refs


def _exchange_input(
    ref: str,
    item: ExchangePositionView,
    config: PositionRiskConfigRow | None,
    instruments: Mapping[str, _InstrumentRiskData],
) -> PositionRiskInput:
    data = instruments[item.inst_id]
    # 用户在本应用里声明的止损优先（那是他明确表达过的意图）；没配过就用同步来的
    # OKX 止损，并原样带上三态——「没查到」与「没挂」在风险层必须分开。
    local_stop = None if config is None else config.stop_px
    if local_stop is not None:
        stop_px, stop_status = local_stop, STOP_CONFIRMED
    else:
        stop_px, stop_status = item.stop_px, item.stop_status
    return PositionRiskInput(
        position_ref=ref,
        source="exchange",
        inst_id=item.inst_id,
        display_symbol=item.display_symbol,
        side=item.pos_side,
        size=item.size,
        inst_type=data.inst_type,
        mark_px=item.mark_px if item.mark_px is not None else data.latest_price,
        stop_px=stop_px,
        stop_status=stop_status,
        atr=data.atr,
        lever=item.lever,
        sector=data.sector,
        ct_val=data.ct_val,
        ct_mult=data.ct_mult,
    )


def _manual_input(
    ref: str,
    item: ManualPositionView,
    config: PositionRiskConfigRow | None,
    instruments: Mapping[str, _InstrumentRiskData],
) -> PositionRiskInput:
    data = instruments[item.inst_id]
    configured_stop = None if config is None else config.stop_px
    return PositionRiskInput(
        position_ref=ref,
        source="manual",
        inst_id=item.inst_id,
        display_symbol=item.display_symbol,
        side=item.side,
        size=item.quantity,
        inst_type=data.inst_type,
        mark_px=item.price if item.price is not None else data.latest_price,
        stop_px=configured_stop if configured_stop is not None else item.stop_px,
        atr=data.atr,
        lever=item.leverage,
        sector=data.sector,
        ct_val=data.ct_val,
        ct_mult=data.ct_mult,
    )


def _load_configs(refs: tuple[str, ...]) -> dict[str, PositionRiskConfigRow]:
    if not refs:
        return {}
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(PositionRiskConfigRow).where(PositionRiskConfigRow.position_ref.in_(refs))
            )
        )
    return {row.position_ref: row for row in rows}


def _instrument_data(symbols: set[str]) -> dict[str, _InstrumentRiskData]:
    """一批标的的持仓风险输入：标的一次、日线一次、最新价一次，都与标的数无关。

    批量读的前提是「来源按标的选」这条规则不变：日线与最新价只按
    `_approved_sources` 认可的来源读，同一标的混存多种来源时仍按顺序挑第一个有数据的，
    不在批量结果里合并。
    """

    if not symbols:
        return {}
    ordered = sorted(symbols)
    known = get_instruments(ordered)
    sources = sorted({source for row in known.values() for source in _approved_sources(row)})
    if not sources:
        return {symbol: _read_instrument(None, symbol, {}, {}) for symbol in ordered}
    series = load_candles_by_source(ordered, DAILY_BAR, sources=sources)
    latest = latest_candles_by_source(ordered, sources=sources)
    return {
        symbol: _read_instrument(known.get(symbol), symbol, series, latest) for symbol in ordered
    }


def _read_instrument(
    row: Instrument | None,
    symbol: str,
    series: Mapping[tuple[str, str], Sequence[Bar]],
    latest: Mapping[tuple[str, str], Bar],
) -> _InstrumentRiskData:
    if row is None:
        return _InstrumentRiskData(None, symbol, None, None, None, None, None)
    approved = _approved_sources(row)
    return _InstrumentRiskData(
        inst_type=row.inst_type,
        display_symbol=f"{row.product_key}-{row.quote_currency}",
        sector=row.sector,
        ct_val=row.ct_val,
        ct_mult=row.ct_mult,
        latest_price=_latest_price(latest, symbol, approved),
        atr=_last_atr(_daily_bars(series, symbol, approved)),
    )


def _daily_bars(
    series: Mapping[tuple[str, str], Sequence[Bar]],
    symbol: str,
    approved: Sequence[str],
) -> tuple[Bar, ...]:
    """按来源顺序取第一个有日线的来源，整段序列原样返回（ATR 需要完整历史）。"""

    for source in approved:
        bars = series.get((symbol, source))
        if bars:
            return tuple(candle for candle in bars if candle.confirm)
    return ()


def _last_atr(bars: tuple[Bar, ...]) -> Decimal | None:
    if len(bars) < ATR_PERIOD:
        return None
    series = compute("atr", bars, {"period": ATR_PERIOD})
    if not series.points:
        return None
    return series.points[-1].values.get("atr")


def _latest_price(
    latest: Mapping[tuple[str, str], Bar],
    symbol: str,
    approved: Sequence[str],
) -> Decimal | None:
    """按来源顺序取第一个有行情的最新收盘价；不限定周期，与 `latest_candle` 同口径。"""

    for source in approved:
        candle = latest.get((symbol, source))
        if candle is not None:
            return candle.close
    return None


def _approved_sources(row: Instrument) -> tuple[str, ...]:
    """风险视图只接受 OKX 落库行情；代理来源不与 OKX 价格混用于 ATR。"""

    return (okx_source(row.inst_type), "okx")


def _thresholds() -> RiskThresholds:
    risk = load_settings().risk
    return RiskThresholds(
        max_leverage=_positive_setting(risk, "max_leverage", "3"),
        max_single_instrument_weight_pct=_positive_setting(
            risk, "max_single_instrument_weight_pct", "35"
        ),
        max_margin_usage_pct=_positive_setting(risk, "max_margin_usage_pct", "70"),
        stop_distance_atr_multiple=_positive_setting(risk, "stop_distance_atr_multiple", "1.0"),
    )


def _positive_setting(risk: Mapping[str, object], name: str, default: str) -> Decimal:
    try:
        value = Decimal(str(risk.get(name, default)))
    except (InvalidOperation, ValueError):
        return Decimal(default)
    return value if value > ZERO else Decimal(default)


def _margin_usage(account: AccountView) -> tuple[Decimal | None, str | None]:
    """保证金占用率只有一种口径：`Σ(名义 ÷ 杠杆) ÷ 权益`。

    不再退回 OKX 的 `used_margin` / `imr`：逐仓模式下它们返回 0 或空，用它会让
    「占用 0%」和「保证金占用过高」这条规则同时失效。`margin_usage_floor` 为真时
    这个比例是下限（有持仓缺行情），界面标 `≥`。
    """

    if account.margin_usage_pct is None:
        return None, None
    return account.margin_usage_pct, "notional_over_leverage"


def _config_view(row: PositionRiskConfigRow) -> SavedRiskConfig:
    return SavedRiskConfig(
        position_ref=row.position_ref,
        stop_px=row.stop_px,
        risk_budget=row.risk_budget,
        warning_threshold_pct=row.warning_threshold_pct,
        source=row.source,
        updated_at=row.updated_at,
    )


def _require_positive(value: object, label: str) -> None:
    if value is _UNSET or value is None:
        return
    if not isinstance(value, Decimal) or value <= ZERO:
        raise UnprocessableEntity(f"{label}必须是大于 0 的十进制数")


def _require_threshold(value: object) -> None:
    if value is _UNSET or value is None:
        return
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO or value > HUNDRED:
        raise UnprocessableEntity("预警阈值必须是 0 到 100 之间的十进制数")
