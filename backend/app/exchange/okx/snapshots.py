"""推送行 → B2 快照结构。

账户与持仓的 REST 快照与 WebSocket 推送字段名不同，但落库口径必须一致。持仓解析
只在这里定义一次：`private.py` 的 REST 快照与 B4 的私有频道推送都调用
`parse_exchange_position_row`，字段映射不会分叉成两套。

账户推送的币种字段在 `details` 数组里，账户级字段与币种级字段分开下发；本模块只做
字段换算，不判断是否配置凭据，也不写库。缺失字段如实留空，不用 0 冒充上游没有
下发的值。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core import AccountSnapshot, ExchangePosition
from app.exchange.errors import ExchangeError

__all__ = [
    "parse_account_snapshot_row",
    "parse_exchange_position_row",
]


def parse_account_snapshot_row(
    row: dict[str, Any],
    *,
    currency: str = "USDT",
) -> AccountSnapshot:
    """把 `account` 频道的一条推送换成账户快照。

    OKX 的 `account` 频道按账户推送，币种字段在 `details` 数组里：账户级的
    `totalEq` / `availEq` / `imr` / `upl` 与币种级的 `cashBal` / `eq` / `availEq`
    分开下发。现金余额只取指定币种的明细，不能用账户级字段顶替；保证金使用率按
    项目统一口径 `已用保证金 / (已用保证金 + 可用权益)` 计算，上游没有足够字段时
    才用 0 到 1 的 `mgnRatio` 兜底。
    """

    detail = _currency_detail(row, currency)
    try:
        equity = _decimal_or_zero(row.get("totalEq"), row.get("adjEq"), detail.get("eq"))
        used_margin = _decimal_or_zero(row.get("imr"), detail.get("imr"))
        available_equity = _decimal_or_none(row.get("availEq"))
        if available_equity is None:
            available_equity = _decimal_or_none(detail.get("availEq"))
        if available_equity is None:
            available_equity = equity - used_margin
        cash_balance = _decimal_or_zero(detail.get("cashBal"))
        unrealized_pnl = _decimal_or_zero(row.get("upl"), detail.get("upl"))
        margin_ratio = _margin_usage_ratio(
            used_margin,
            available_equity,
            _first_decimal(row.get("mgnRatio"), detail.get("mgnRatio")),
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"账户推送数据非法:{row!r}") from exc

    return AccountSnapshot(
        currency=currency,
        equity=equity,
        available_equity=available_equity,
        cash_balance=cash_balance,
        unrealized_pnl=unrealized_pnl,
        used_margin=used_margin,
        available_margin=available_equity,
        margin_ratio=margin_ratio,
    )


def parse_exchange_position_row(row: dict[str, Any]) -> ExchangePosition:
    """把 `positions` 频道的一行换成与 REST 相同的持仓快照。

    数量为 0 的持仓由调用方过滤；这里只拒绝缺少标的的异常行。
    """

    try:
        pos = _decimal(row.get("pos") or "0")
        inst_id = str(row["instId"])
        side = _position_side(row, pos)
        return ExchangePosition(
            pos_id=str(row.get("posId") or f"{inst_id}:{side}"),
            inst_id=inst_id,
            pos_side=side,
            size=abs(pos),
            avg_px=_decimal(row.get("avgPx") or "0"),
            mark_px=_decimal_or_none(row.get("markPx")),
            upl=_decimal_or_none(row.get("upl")),
            upl_ratio=_decimal_or_none(row.get("uplRatio")),
            lever=_decimal_or_none(row.get("lever")),
            mgn_mode=_text_or_none(row.get("mgnMode")),
            liq_px=_decimal_or_none(row.get("liqPx")),
            margin=_decimal_or_none(row.get("margin")),
        )
    except KeyError as exc:
        raise ExchangeError(f"持仓推送缺少字段:{exc}") from exc
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"持仓推送数据非法:{row!r}") from exc


def _currency_detail(row: dict[str, Any], currency: str) -> dict[str, Any]:
    """取出指定币种的账户明细；`details` 缺失或没有该币种时返回空映射。"""

    details = row.get("details")
    if not isinstance(details, list):
        return {}
    for item in details:
        if isinstance(item, dict) and str(item.get("ccy") or "") == currency:
            return item
    return {}


def _position_side(row: dict[str, Any], pos: Decimal) -> str:
    """`posSide` 归一化为 `long` / `short`；单向模式的 `net` 按数量符号拆分。"""

    side = str(row.get("posSide") or "").strip().lower()
    if side in {"long", "short"}:
        return side
    return "long" if pos > 0 else "short"


def _margin_usage_ratio(
    used_margin: Decimal,
    available_margin: Decimal,
    fallback: Decimal | None,
) -> Decimal:
    """保证金使用率：0 到 1。上游没有足够字段时用 `mgnRatio` 兜底。"""

    denominator = used_margin + available_margin
    if denominator > 0:
        return used_margin / denominator
    if fallback is not None and Decimal(0) <= fallback <= Decimal(1):
        return fallback
    return Decimal(0)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or str(value) == "":
        return None
    return _decimal(value)


def _first_decimal(*values: Any) -> Decimal | None:
    for value in values:
        parsed = _decimal_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _decimal_or_zero(*values: Any) -> Decimal:
    for value in values:
        parsed = _decimal_or_none(value)
        if parsed is not None:
            return parsed
    return Decimal(0)


def _text_or_none(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text or None
