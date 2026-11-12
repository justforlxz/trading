"""账户结算入口：一次调用同时算资金费、保证金占用与被强平的腿。

引擎在每根 bar 的结算步只调用一个入口，本模块回答三件事：

- **资金费**：交给 `FundingSettlement` 账本按结算网格计现金流；
- **保证金占用**：按标的类别的交易规则折算名义金额，再用该标的的档位表取杠杆与维持
  保证金率，占用额 = 名义金额 / 杠杆（`margin.margin_used`）；
- **强平**：同一份档位表给出强平价；本 bar 的最低价（多仓）或最高价（空仓）穿过它，
  这条腿就在这根 bar 上被强平，强平价原样回传给引擎平仓。

保证金只占用不划转，因此它不进 `cash`，单独作为 `SettlementOutcome.margin_used` 回传
给引擎记账；现金变动只有资金费。

## 档位表

`tiers` 以产品键为键：上游按 `instFamily` 下发档位表，不同标的的档位不能互相借用。
有保证金的腿没有档位表时直接报错，而不是按「没有保证金」处理——那会把占用额静默记成
0，看起来和「杠杆无限大」一样。

## 复用

本入口自身不带累计状态，累计状态在 `FundingSettlement` 账本里。`begin_run()` 把边界
交给账本：`run_backtest` 在进入 bar 循环前调用它，因此同一实例跨两次回测复用时，第二
次的结果与新建实例相同（见 `FundingSettlement.begin_run`）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.backtest.funding_cost import FundingSettlement
from app.backtest.margin import (
    DEFAULT_MAX_LEVERAGE,
    PositionTier,
    liquidated_in_bar,
    margin_terms,
    margin_used,
)
from app.backtest.simulation import (
    LegLiquidation,
    LegPosition,
    Settlement,
    SettlementOutcome,
)
from app.core import Bar, InstrumentRef, ValidationError
from app.instrument import trading_rules

__all__ = ["AccountSettlement"]

ZERO = Decimal(0)


class AccountSettlement:
    """引擎的结算入口：本 bar 的资金费现金、保证金占用与被强平的腿。

    - `instruments` 与 `BacktestInput.instruments` 同一份映射，用来判断每条腿的类别；
    - `tiers` 以产品键为键，值是该标的的杠杆档位表；有保证金的腿必须有表；
    - `funding` 是资金费账本，为 `None` 时本 bar 不产生资金费现金流；
    - `max_leverage` 是本地上限，实际杠杆还要被档位与硬上限压住（`margin.effective_leverage`）。
    """

    def __init__(
        self,
        *,
        instruments: Mapping[str, InstrumentRef],
        tiers: Mapping[str, Sequence[PositionTier]],
        funding: FundingSettlement | None = None,
        max_leverage: Decimal = DEFAULT_MAX_LEVERAGE,
    ) -> None:
        self._instruments = dict(instruments)
        self._tiers = {key: tuple(table) for key, table in tiers.items()}
        self._funding = funding
        self._max_leverage = max_leverage

    def __call__(self, state: Settlement) -> SettlementOutcome:
        """结算 `state.moment` 这一根 bar：资金费现金、保证金占用与强平事实。"""

        cash = self._funding(state) if self._funding is not None else ZERO
        occupied = ZERO
        liquidated: list[LegLiquidation] = []
        for position in state.positions:
            instrument = _instrument(self._instruments, position)
            terms = margin_terms(
                inst_type=instrument.inst_type,
                side=position.side,
                entry_price=position.entry_price,
                size=position.qty,
                max_leverage=self._max_leverage,
                tiers=self._tiers_for(instrument, position),
            )
            occupied += margin_used(terms, position.notional(_price(state, position)))
            if terms.liquidation_price is None:
                continue
            candle = _bar(state, position)
            hit = liquidated_in_bar(
                side=position.side,
                liquidation_price=terms.liquidation_price,
                high=candle.high,
                low=candle.low,
            )
            if hit:
                liquidated.append(
                    LegLiquidation(
                        product_key=position.product_key,
                        side=position.side,
                        price=terms.liquidation_price,
                        bar_open_time=state.moment,
                    )
                )

        return SettlementOutcome(
            cash=cash,
            margin_used=occupied,
            liquidated=tuple(liquidated),
            funding_report=self._funding.report() if self._funding is not None else None,
        )

    def begin_run(self) -> None:
        """开始一次新的回测：重置资金费账本的累计状态。本入口自身没有累计状态。"""

        if self._funding is not None:
            self._funding.begin_run()

    def _tiers_for(
        self,
        instrument: InstrumentRef,
        position: LegPosition,
    ) -> Sequence[PositionTier]:
        """该腿的档位表；现货不占用保证金，不需要档位。"""

        if not trading_rules(instrument.inst_type).has_margin:
            return ()
        table = self._tiers.get(position.product_key)
        if table is None:
            raise ValidationError(f"标的 {position.product_key} 没有杠杆档位表, 无法计算保证金占用")
        return table


def _instrument(
    instruments: Mapping[str, InstrumentRef],
    position: LegPosition,
) -> InstrumentRef:
    instrument = instruments.get(position.product_key)
    if instrument is None:
        raise ValidationError(f"标的 {position.product_key} 没有标的静态信息, 无法计算保证金与强平")
    return instrument


def _price(state: Settlement, position: LegPosition) -> Decimal:
    price = state.prices.get(position.product_key)
    if price is None:
        raise ValidationError(f"标的 {position.product_key} 在结算时刻没有可用价格")
    return price


def _bar(state: Settlement, position: LegPosition) -> Bar:
    candle = state.bars.get(position.product_key)
    if candle is None:
        raise ValidationError(
            f"标的 {position.product_key} 在该结算时刻没有本 bar 行情, 无法判定强平"
        )
    return candle
