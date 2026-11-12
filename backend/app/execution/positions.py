"""账户实际持仓：执行侧唯一的「实际持仓」层。

## 两层持仓不混用

| 层 | 归谁 |
| --- | --- |
| 策略级虚拟持仓（每个策略实例自己的成本、盈亏） | 全局组合管理（T7.1） |
| 账户实际持仓（交易所侧或 paper 侧真实存在的数量与成本） | 本模块 |

本模块不记盈亏归属、不分摊资金、不做对账：这些分别属于组合管理、风险与对账恢复。

## 两类持仓，同一种形状

- **永续**：上游持仓接口直接给数量、成本、持仓方向、杠杆、保证金与强平价。
- **现货**：主要交易对没有持仓接口，持仓由余额明细推导（口径见 `T5.1`：可用量 +
  冻结量，成本取上游 `avgPx`，没有就记 0 表示未知）；现货只有多头，负数量在本模块
  不成立。

两类都归一成 `AccountPosition`，字段集合完全相同，上层不感知类别差异。现货的
`pos_side` / `leverage` / `margin` / `liq_price` 一律是 `None`——**不用 0 冒充
「没有这个字段」**：0 会被下游当成有效值参与比较（现货保证金 0 与「现货没有保证金
这件事」是两回事）。

`None` 的第二层含义是「不知道」：永续上游没下发、模拟账户不模拟保证金或强平时，
这几个字段同样保持 `None`，不填 0。

## 数量与方向

`qty` 恒为正的绝对值，方向在 `side`（`long` / `short`）。上游 `core.Position.qty`
带符号（正多负空），把这一个换算点收在本模块里。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.core import Fill, Position, ValidationError
from app.execution.errors import PaperRejected
from app.execution.orders import POS_SIDES
from app.instrument import Instrument, trading_categories, trading_rules

__all__ = [
    "NET_POS_SIDE",
    "SIDE_LONG",
    "SIDE_SHORT",
    "AccountPosition",
    "PositionBook",
    "from_venue_position",
]

SIDE_LONG = "long"
SIDE_SHORT = "short"
#: 单向持仓模式（上游 `net`）：一个标的同时只有一条腿。
NET_POS_SIDE = "net"

_FILL_SIDES = frozenset({"buy", "sell"})
_SIDES = frozenset({SIDE_LONG, SIDE_SHORT})
_SWAP_COLUMNS = ("pos_side", "leverage", "margin", "liq_price")
ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class AccountPosition:
    """账户里的一条实际持仓（同一产品的同一方向一条）。

    `product_key` 而不是 `inst_id`：同一产品的现货与永续在持仓这一层不再区分形态，
    对账、求差与风险都按产品比较；具体形态仍在 `inst_type` 里，需要时再取。
    """

    product_key: str
    inst_type: str
    side: str
    qty: Decimal
    avg_cost: Decimal
    pos_side: str | None = None
    leverage: Decimal | None = None
    margin: Decimal | None = None
    liq_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.product_key.strip():
            raise ValidationError("持仓必须给出 product_key")
        if not self.inst_type.strip():
            raise ValidationError("持仓必须给出 inst_type")
        if self.side not in _SIDES:
            raise ValidationError(f"持仓方向必须是 {sorted(_SIDES)}, 实际 {self.side!r}")
        if self.qty <= ZERO:
            raise ValidationError(f"持仓数量必须为正, 实际 {self.qty}")
        if self.avg_cost < ZERO:
            raise ValidationError(f"持仓成本不能为负, 实际 {self.avg_cost}")
        if self.inst_type not in trading_categories():
            raise ValidationError(f"标的类别 {self.inst_type!r} 没有注册交易规则")
        if self.inst_type == "SPOT":
            _require_spot_columns(self)
        else:
            _require_swap_columns(self)


def from_venue_position(
    position: Position,
    instrument: Instrument,
    *,
    pos_side: str | None = None,
    leverage: Decimal | None = None,
    margin: Decimal | None = None,
    liq_price: Decimal | None = None,
) -> AccountPosition:
    """把交易所侧的一条持仓（`core.Position`）归一成本模块的形状。

    上游持仓量带符号，这里拆成 `side` 与正数 `qty`。永续的持仓方向、杠杆、保证金与
    强平价由调用方按上游应答传入：`core.Position` 只有数量、成本与未实现盈亏，
    这三项不在其中，也不在本模块拼字符串或猜默认值。

    `position.qty` 为 0 的行不该出现在持仓列表里（上游本来就不返回无持仓的标的），
    真出现了说明上游或适配层有问题，按参数不合法报错而不是悄悄丢掉。
    """

    if position.inst_id != instrument.symbol:
        raise ValidationError(
            f"持仓的标的 {position.inst_id} 与标的行 {instrument.symbol} 不一致, 不能拿错配对归一"
        )
    if position.qty == ZERO:
        raise ValidationError(f"标的 {position.inst_id} 的持仓量为 0, 不该出现在持仓列表里")
    return AccountPosition(
        product_key=instrument.product_key,
        inst_type=instrument.inst_type,
        side=SIDE_LONG if position.qty > ZERO else SIDE_SHORT,
        qty=abs(position.qty),
        avg_cost=position.avg_price,
        pos_side=pos_side,
        leverage=leverage,
        margin=margin,
        liq_price=liq_price,
    )


class PositionBook:
    """paper 侧的账户实际持仓：按成交逐笔记账。

    只回答「现在持有什么、成本多少、数量多少」：加仓按成交量加权成本，减仓扣数量、
    成本不变，减到 0 就删掉这一条。已实现盈亏、资金收付、保证金结算与强平不在本层
    （分别属于组合管理、风险与回测/交易所口径）。

    「腿」怎么分：

    - 现货：只有多头，买入加仓、卖出减仓；超卖抛 `PaperRejected`，不记空头。
    - 永续对冲模式（`pos_side` 为 `long` / `short`）：腿由 `pos_side` 给出，同一产品
      可以同时有多空两条腿；方向与腿一致的成交是加仓，相反的成交必须带
      `reduce_only`（那是平仓），否则报错而不是悄悄记到另一条腿上。
    - 永续单向模式（`pos_side` 留空或 `net`）：同一产品只有一条腿——成交方向与已有腿
      相反时先减仓，减完还有余量才用余量开反向腿。
    """

    def __init__(self) -> None:
        self._positions: dict[tuple[str, str, str], AccountPosition] = {}

    def apply(
        self,
        fill: Fill,
        instrument: Instrument,
        *,
        pos_side: str = "",
        reduce_only: bool = False,
    ) -> None:
        """记一笔成交；账本拒绝这笔成交时抛错，且不留下半条持仓。"""

        if fill.side not in _FILL_SIDES:
            raise ValidationError(f"成交方向必须是 {sorted(_FILL_SIDES)}, 实际 {fill.side!r}")
        if fill.qty <= ZERO:
            raise ValidationError(f"成交量必须为正, 实际 {fill.qty}")
        if trading_rules(instrument.inst_type).has_margin:
            if pos_side in _SIDES:
                self._apply_hedged(instrument, fill, pos_side=pos_side, reduce_only=reduce_only)
            else:
                self._apply_net(instrument, fill, reduce_only=reduce_only)
            return
        if pos_side or reduce_only:
            raise ValidationError("现货没有 pos_side / reduce_only, 这两个参数只属于永续")
        if fill.side == "buy":
            self._open(instrument, SIDE_LONG, qty=fill.qty, price=fill.price, pos_side=None)
            return
        self._close(instrument, SIDE_LONG, qty=fill.qty, inst_id=fill.inst_id)

    def positions(self) -> tuple[AccountPosition, ...]:
        """按产品、类别、方向排序返回，便于逐字段比较。"""

        return tuple(self._positions[key] for key in sorted(self._positions))

    def _apply_hedged(
        self,
        instrument: Instrument,
        fill: Fill,
        *,
        pos_side: str,
        reduce_only: bool,
    ) -> None:
        """对冲模式：腿由 `pos_side` 给出，方向相反的成交就是平仓。"""

        opening_side = SIDE_LONG if fill.side == "buy" else SIDE_SHORT
        if pos_side == opening_side:
            if reduce_only:
                raise ValidationError(f"只减仓单的方向与持仓方向相同, 那是加仓:{pos_side}")
            self._open(instrument, pos_side, qty=fill.qty, price=fill.price, pos_side=pos_side)
            return
        if not reduce_only:
            raise ValidationError(
                f"开仓方向 {fill.side} 与持仓方向 {pos_side} 不一致; 平仓请带 reduce_only"
            )
        self._close(instrument, pos_side, qty=fill.qty, inst_id=fill.inst_id)

    def _apply_net(self, instrument: Instrument, fill: Fill, *, reduce_only: bool) -> None:
        """单向模式：一个产品一条腿，先对冲已有的反向腿，余量才开新腿。"""

        opening_side = SIDE_LONG if fill.side == "buy" else SIDE_SHORT
        closing_side = _other(opening_side)
        held = self._positions.get(self._key(instrument, closing_side))
        held_qty = ZERO if held is None else held.qty
        if reduce_only:
            # 只减仓不能反手开仓：可减量不足时整笔拒绝，不先扣掉一半数量。
            if fill.qty > held_qty:
                raise PaperRejected(
                    f"{fill.inst_id} 可减持仓 {held_qty}, 成交 {fill.qty} 超过持有量"
                )
            self._close(instrument, closing_side, qty=fill.qty, inst_id=fill.inst_id)
            return
        remaining = fill.qty
        if held is not None:
            closed = min(held.qty, remaining)
            self._close(instrument, closing_side, qty=closed, inst_id=fill.inst_id)
            remaining -= closed
        if remaining > ZERO:
            self._open(
                instrument, opening_side, qty=remaining, price=fill.price, pos_side=NET_POS_SIDE
            )

    def _open(
        self,
        instrument: Instrument,
        side: str,
        *,
        qty: Decimal,
        price: Decimal,
        pos_side: str | None,
    ) -> None:
        """加仓：新成本 = (原数量 × 原成本 + 本次成交量 × 成交价) / 新数量。"""

        key = self._key(instrument, side)
        current = self._positions.get(key)
        if current is None:
            self._positions[key] = AccountPosition(
                product_key=instrument.product_key,
                inst_type=instrument.inst_type,
                side=side,
                qty=qty,
                avg_cost=price,
                pos_side=pos_side,
            )
            return
        total = current.qty + qty
        cost = (current.qty * current.avg_cost + qty * price) / total
        self._positions[key] = replace(current, qty=total, avg_cost=cost)

    def _close(self, instrument: Instrument, side: str, *, qty: Decimal, inst_id: str) -> None:
        """减仓：先校验够不够减，再扣数量；扣到 0 就删掉这一条。"""

        key = self._key(instrument, side)
        current = self._positions.get(key)
        if current is None:
            raise PaperRejected(f"没有 {inst_id} 的持仓可减, 却来了 {qty} 的成交")
        if qty > current.qty:
            raise PaperRejected(f"{inst_id} 可减持仓 {current.qty}, 成交 {qty} 超过持有量")
        remaining = current.qty - qty
        if remaining == ZERO:
            del self._positions[key]
            return
        self._positions[key] = replace(current, qty=remaining)

    @staticmethod
    def _key(instrument: Instrument, side: str) -> tuple[str, str, str]:
        return (instrument.product_key, instrument.inst_type, side)


def _other(side: str) -> str:
    return SIDE_SHORT if side == SIDE_LONG else SIDE_LONG


def _require_spot_columns(position: AccountPosition) -> None:
    """现货的两条约定：四个永续字段是 `None`，方向只有多头。

    用 0 冒充「没有这个字段」会让下游把「没有」当成「等于 0」；记一条现货空头同样不行——
    现货没有持仓接口也没有做空，空头只可能来自记错符号或拿错标的。
    """

    present = [name for name in _SWAP_COLUMNS if getattr(position, name) is not None]
    if present:
        raise ValidationError(f"现货持仓没有 {', '.join(present)}, 必须是 None 而不是 0")
    if position.side != SIDE_LONG:
        raise ValidationError("现货只有多头持仓: 现货空头不在本模块的建模范围内")


def _require_swap_columns(position: AccountPosition) -> None:
    """永续必须有持仓方向；其余三项可以缺（未知），但给了就必须落在合法范围。"""

    if position.pos_side not in POS_SIDES:
        raise ValidationError(f"永续持仓方向必须是 {sorted(POS_SIDES)}, 实际 {position.pos_side!r}")
    if position.leverage is not None and position.leverage < ONE:
        raise ValidationError(f"杠杆必须不小于 1, 实际 {position.leverage}")
    if position.margin is not None and position.margin < ZERO:
        raise ValidationError(f"保证金不能为负, 实际 {position.margin}")
    if position.liq_price is not None and position.liq_price <= ZERO:
        raise ValidationError(f"强平价必须为正, 实际 {position.liq_price}")
