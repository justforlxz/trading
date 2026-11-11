"""资金费结算：按 8 小时结算点把资金费计入持仓 PnL（纯函数 + 一个结算账本）。

上游费率是「每个结算点的一次性现金流」，不是按秒累计的年化利率。因此结算只发生在
UTC 的 8 小时网格上（00:00 / 08:00 / 16:00），两次结算之间为 0。网格步长取本类别
规则表里的 `funding_interval_hours`：现货没有资金费（`has_funding` 为假），结算入口
对它恒返回 0。

## 计费口径

- 名义金额 × 费率：正费率多头付出、空头收取；负费率反过来。
- 费率优先取 `realized_rate`，缺失回退 `funding_rate`；两者都缺失时记为
  `funding_missing`，绝不按 0 计费（D2 实施约束）。
- 窗口内应当有记录却整条缺失的「结算点 × 持仓腿」记为 `missing_points`。
- 费率确实为 0 的记录是有效样本：现金流为 0，单独记为 `rate_zero`，与「数据缺失」
  区分开。

## 结算时刻

引擎每根 bar 调一次结算入口，因此账本自己维护「上一次结算到哪」，把两次调用之间落在
网格上的结算点一次结清：1D 的 bar 会一次结掉当天 3 个结算点，而不是只结整点那一个。
每条腿只结算它开仓之后的结算点（`entry_time` 之前的不计），所以平仓后重新开仓不会把
空仓期间的结算点补扣回来。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.backtest.simulation import LONG, LegPosition, Settlement
from app.core import InstrumentRef, ValidationError
from app.instrument import trading_rules
from app.market import FundingPoint

__all__ = [
    "FundingReport",
    "FundingSettlement",
    "funding_points_between",
    "on_funding_grid",
]

ONE = Decimal(1)
ZERO = Decimal(0)
HUNDRED = Decimal(100)

#: 结算网格的锚点：UTC 零点。所有结算点都是它的整数倍小时。
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: 覆盖率保留两位小数；契约里的 `funding_coverage_pct` 是十进制文本。
COVERAGE_SCALE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class FundingReport:
    """一次回测的资金费结果与覆盖率。

    `expected_points` 按「结算点 × 持仓腿」计数：同一结算点上持有两条永续腿就是两个
    点。三个缺口计数器互不重叠，`covered_points = expected - missing - funding_missing`。
    """

    total: Decimal
    expected_points: int
    missing_points: int
    funding_missing: int
    rate_zero: int

    @property
    def covered_points(self) -> int:
        """拿到可用费率的结算点（含费率确实为 0 的那些）。"""

        return self.expected_points - self.missing_points - self.funding_missing

    @property
    def coverage_pct(self) -> Decimal | None:
        """费率覆盖率百分比；窗口内没有需要结算的点时为 `None`。"""

        if self.expected_points == 0:
            return None
        return (Decimal(self.covered_points) / Decimal(self.expected_points) * HUNDRED).quantize(
            COVERAGE_SCALE, rounding=ROUND_HALF_UP
        )


def on_funding_grid(moment: datetime, interval_hours: int) -> bool:
    """该时刻是否正好落在结算网格上。"""

    _require_aware(moment, "结算时刻")
    step = _require_interval(interval_hours)
    return _is_on_grid(moment, step)


def funding_points_between(
    start: datetime,
    end: datetime,
    interval_hours: int,
) -> tuple[datetime, ...]:
    """`(start, end]` 之间落在结算网格上的时刻，按时间升序。

    左开右闭：`start` 这一刻已经结过，不重复计费；`end` 这一刻属于本次调用。
    """

    _require_aware(start, "起点")
    _require_aware(end, "终点")
    step = _require_interval(interval_hours)
    if end <= start:
        return ()

    hours = int((start - EPOCH).total_seconds() // 3600)
    anchor = EPOCH + timedelta(hours=(hours // step) * step)
    moment = anchor if anchor > start else anchor + timedelta(hours=step)

    points: list[datetime] = []
    while moment <= end:
        points.append(moment)
        moment += timedelta(hours=step)
    return tuple(points)


class FundingSettlement:
    """按类别结算资金费的入口：实例本身可调用，直接交给引擎的 `settle`。

    - `instruments` 与 `BacktestInput.instruments` 同一份映射，用来判断每条腿的类别
      与结算步长；
    - `rates` 以上游 `instId` 为键（资金费表落的就是 `inst_id`），值为该标的的费率点；
    - `enabled` 默认开启（D2）；关闭时恒返回 0，也不累计计数器。

    引擎在空仓时不会调用结算入口，因此账本在每次调用后记录本次时刻，只结算
    `(上次时刻, 本次时刻]` 之间的网格点；尚无上次时刻时从本次持仓的最早开仓时刻算起。
    """

    def __init__(
        self,
        *,
        instruments: Mapping[str, InstrumentRef],
        rates: Mapping[str, Iterable[FundingPoint]] | None = None,
        enabled: bool = True,
    ) -> None:
        self._instruments = dict(instruments)
        self._rates = {
            inst_id: {point.funding_time: point for point in points}
            for inst_id, points in (rates or {}).items()
        }
        self._enabled = enabled
        self._last: datetime | None = None
        self._total = ZERO
        self._expected = 0
        self._missing = 0
        self._funding_missing = 0
        self._rate_zero = 0

    def __call__(self, state: Settlement) -> Decimal:
        """结算 `Settlement.moment` 及其之前尚未结算的结算点，返回现金变动。"""

        moment = state.moment
        _require_aware(moment, "结算时刻")
        holdings = self._holdings(state)
        if not self._enabled or not holdings:
            self._last = moment
            return ZERO

        start = self._last
        if start is None:
            start = min(position.entry_time for _, position, _ in holdings)

        cash = ZERO
        for interval, legs in _by_interval(holdings).items():
            for point in funding_points_between(start, moment, interval):
                for instrument, position, notional in legs:
                    if point <= position.entry_time:
                        continue
                    cash += self._charge(instrument, position, notional, point)
        self._last = moment
        return cash

    def report(self) -> FundingReport:
        """目前已累计的资金费与覆盖率。"""

        return FundingReport(
            total=self._total,
            expected_points=self._expected,
            missing_points=self._missing,
            funding_missing=self._funding_missing,
            rate_zero=self._rate_zero,
        )

    def _holdings(
        self, state: Settlement
    ) -> tuple[tuple[InstrumentRef, LegPosition, Decimal], ...]:
        """本 bar 需要计资金费的腿：按类别规则筛选，并记下按结算价算出的名义金额。"""

        holdings: list[tuple[InstrumentRef, LegPosition, Decimal]] = []
        for position in state.positions:
            instrument = self._instruments.get(position.product_key)
            if instrument is None:
                raise ValidationError(
                    f"标的 {position.product_key} 没有标的静态信息, 无法结算资金费"
                )
            if not trading_rules(instrument.inst_type).has_funding:
                continue
            price = state.prices.get(position.product_key)
            if price is None:
                raise ValidationError(f"标的 {position.product_key} 在结算时刻没有可用价格")
            holdings.append((instrument, position, position.notional(price)))
        return tuple(holdings)

    def _charge(
        self,
        instrument: InstrumentRef,
        position: LegPosition,
        notional: Decimal,
        point: datetime,
    ) -> Decimal:
        """一个持仓腿在一个结算点上的现金流；缺失与真 0 分开记账。"""

        self._expected += 1
        recorded = self._rates.get(instrument.inst_id)
        row = recorded.get(point) if recorded is not None else None
        if row is None:
            self._missing += 1
            return ZERO
        rate = row.realized_rate if row.realized_rate is not None else row.funding_rate
        if rate is None:
            self._funding_missing += 1
            return ZERO
        if rate == ZERO:
            self._rate_zero += 1
            return ZERO

        sign = ONE if position.side == LONG else -ONE
        cash = -sign * notional * rate
        self._total += cash
        return cash


def _by_interval(
    holdings: Iterable[tuple[InstrumentRef, LegPosition, Decimal]],
) -> dict[int, list[tuple[InstrumentRef, LegPosition, Decimal]]]:
    """按结算步长分组：不同类别可能有不同的结算周期。"""

    grouped: dict[int, list[tuple[InstrumentRef, LegPosition, Decimal]]] = {}
    for holding in holdings:
        interval = trading_rules(holding[0].inst_type).funding_interval_hours
        if interval is None:
            raise ValidationError(f"标的类别 {holding[0].inst_type!r} 没有资金费结算周期")
        grouped.setdefault(_require_interval(interval), []).append(holding)
    return grouped


def _is_on_grid(moment: datetime, interval_hours: int) -> bool:
    if moment.minute or moment.second or moment.microsecond:
        return False
    hours = int((moment - EPOCH).total_seconds() // 3600)
    return hours % interval_hours == 0


def _require_interval(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"资金费结算周期必须是正整数小时, 实际 {value!r}")
    return value


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(f"{name} 必须带时区")
    return value
