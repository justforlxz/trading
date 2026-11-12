"""批量回测的排序与交易次数过滤：同一策略跑多个标的后，把结果摆成一排比较。

## 只排序，不判定

`rank_rows` 只改变顺序，不给任何一行加「最优」标记。把历史收益最高的标的或参数组合
标成最优，等于把「过去涨得好」写成「以后也该选它」，过拟合就是这样进的结论。并列的
结果保持入参顺序（`sorted` 是稳定排序）；名次只由被排序的那一个指标决定，不引入第二
把尺子（「收益并列时按 Sharpe 打破」等于又偷偷挑了一次）。

调用方要展示哪几段区间、哪几项指标，由行自己带着：本模块不读库、不读行情，也不认
数据源。代理数据与 OKX 实盘标的不可比，跨源排序必须在调本模块之前就排除。

## 过滤

`min_trades` 只按被排序那一行的交易次数过滤：交易次数不足的结果进排行榜，会让「只做
了两笔却恰好都赚」的组合压过「做了一百笔、期望为正」的组合。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

from app.core import ValidationError

__all__ = ["rank_rows"]

#: 排行榜可用的四个排序指标，名字与 `metrics.compute_metrics` 的键一致。
RANKING_METRICS: tuple[str, ...] = (
    "total_return",
    "max_drawdown",
    "sharpe",
    "profit_factor",
)

#: 过滤用的指标名；`compute_metrics` 给的交易次数是 Decimal，比较前不转成整数。
TRADE_COUNT_METRIC = "trade_count"

#: 越大越好的指标。`max_drawdown` 是正数幅度（0.1 表示从峰值回撤 10%），越小越好，
#: 因此不在这张表里——按它排序时是升序。
_DESCENDING: frozenset[str] = frozenset({"total_return", "sharpe", "profit_factor"})


def rank_rows[RowT](
    rows: Sequence[RowT],
    *,
    metric: str,
    metrics_of: Callable[[RowT], Mapping[str, Decimal]],
    min_trades: int = 0,
) -> tuple[RowT, ...]:
    """按 `metric` 给行排序，丢掉交易次数低于 `min_trades` 的行，返回原对象。

    `metrics_of` 把一行读成一个指标映射（键与 `compute_metrics` 一致）：排序键与过滤键
    都从同一份映射里取，不要求调用方为每行再做一次派生计算。返回的是入参里的那些对象
    本身，顺序变了、身份没变，因此调用方仍能拿到行上除指标以外的字段。

    缺少排序指标、指标不是有限定点数、交易次数下限为负或不是整数，一律判错而不是
    跳过：默认跳过会把「数据有问题」显示成「这一行不参与排名」。
    """

    if metric not in RANKING_METRICS:
        raise ValidationError(f"未知排序指标 {metric!r}; 可选 {list(RANKING_METRICS)}")
    if isinstance(min_trades, bool) or not isinstance(min_trades, int):
        raise ValidationError(f"交易次数下限必须是整数, 实际 {min_trades!r}")
    if min_trades < 0:
        raise ValidationError(f"交易次数下限不能为负, 实际 {min_trades}")

    readings: list[tuple[Decimal, RowT]] = []
    for index, row in enumerate(rows):
        metrics = metrics_of(row)
        if not isinstance(metrics, Mapping):
            raise ValidationError(f"第 {index} 行的指标不是映射")
        value = _metric_value(metrics, metric, index=index)
        if min_trades and _metric_value(metrics, TRADE_COUNT_METRIC, index=index) < min_trades:
            continue
        readings.append((value, row))

    readings.sort(key=lambda item: item[0], reverse=metric in _DESCENDING)
    return tuple(row for _, row in readings)


def _metric_value(metrics: Mapping[str, Decimal], name: str, *, index: int) -> Decimal:
    """取一行的一个指标值；缺键或不是有限定点数都判错，并说清是哪一行。"""

    if name not in metrics:
        raise ValidationError(f"第 {index} 行缺少指标 {name}")
    value = metrics[name]
    if not isinstance(value, Decimal):
        raise ValidationError(
            f"第 {index} 行的指标 {name} 必须是 Decimal, 实际 {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValidationError(f"第 {index} 行的指标 {name} 不是有限数: {value}")
    return value
