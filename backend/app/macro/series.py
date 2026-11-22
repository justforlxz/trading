"""宏观序列清单：有哪些序列、显示名称与单位、支持哪几个粒度。

序列标识进数据库主键，因此清单写在代码里而不是配置里：改名等于改数据。
「用哪个 provider 抓」不在这里固定，来自 `settings.data_sources.macro.series`。

粒度只有两个取值：`minute`（调度器每分钟拉一次）与 `daily`（日线结算值，每天最多
一行）。`us2y` 只有日线——免费源里没有 2Y 的分钟级数据，它只服务于 2Y→10Y 利差。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "DEFAULT_PROVIDERS",
    "GRANULARITY_DAILY",
    "GRANULARITY_MINUTE",
    "SERIES",
    "SERIES_BY_ID",
    "SERIES_PROVIDERS",
    "SeriesSpec",
    "quantize_value",
]

GRANULARITY_MINUTE = "minute"
GRANULARITY_DAILY = "daily"


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """一个宏观序列的固定定义。`granularities` 声明它需要哪几个粒度。"""

    series_id: str
    name: str
    unit: str
    granularities: tuple[str, ...]
    #: 落库与展示的小数位。上游给的浮点数（例如 Yahoo 的 4.911999702453613）先按它取整，
    #: 不把二进制浮点的尾巴写进库、也不让它出现在首页。
    precision: int


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        series_id="us10y",
        name="美国 10 年期国债",
        unit="%",
        granularities=(GRANULARITY_MINUTE, GRANULARITY_DAILY),
        precision=3,
    ),
    SeriesSpec(
        series_id="us2y",
        name="美国 2 年期国债",
        unit="%",
        granularities=(GRANULARITY_DAILY,),
        precision=3,
    ),
    SeriesSpec(
        series_id="vix",
        name="恐慌指数 VIX",
        unit="点",
        granularities=(GRANULARITY_MINUTE, GRANULARITY_DAILY),
        precision=2,
    ),
)
SERIES_BY_ID: dict[str, SeriesSpec] = {spec.series_id: spec for spec in SERIES}


def quantize_value(series_id: str, value: Decimal) -> Decimal:
    """按该序列的小数位取整；上游的浮点尾巴在入库前就抹掉。"""

    precision = SERIES_BY_ID[series_id].precision
    return value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


#: 每个序列**每个粒度**允许的 provider：数据源能力按粒度区分，不是按序列区分。
#:
#: 分钟级只能由分钟级源服务（`yahoo`），日结只能由结算源服务（财政部 CSV、CBOE CSV）：
#: 把日结槽配成 `yahoo` 会让利差用「分钟级 10Y 减日线 2Y」，把分钟槽配成 `treasury`
#: 会把日结算值当成盘中读数，两者都违反工单的 MUST NOT。
#:
#: `vix.minute` 同时允许 `cboe` 与 `yahoo`：AC1 要求设置页能在两个 provider 之间切换
#: `vix.minute`，切换后仍要入库，因此 `cboe` 必须留在它的分钟槽里；两个粒度指向同一批
#: 数据这一点已作为「是否增加粒度列」的待决事项交给 PL。
SERIES_PROVIDERS: dict[str, dict[str, tuple[str, ...]]] = {
    "us10y": {GRANULARITY_MINUTE: ("yahoo",), GRANULARITY_DAILY: ("treasury",)},
    "us2y": {GRANULARITY_DAILY: ("treasury",)},
    "vix": {
        GRANULARITY_MINUTE: ("cboe", "yahoo"),
        GRANULARITY_DAILY: ("cboe",),
    },
}

#: 每个序列每个粒度的默认 provider。设置里缺项时用它；与
#: `app.settings` 的 `DEFAULT_DATA_SOURCES` 由测试断言保持一致，两处不会各说各话。
DEFAULT_PROVIDERS: dict[str, dict[str, str]] = {
    "us10y": {GRANULARITY_MINUTE: "yahoo", GRANULARITY_DAILY: "treasury"},
    "us2y": {GRANULARITY_DAILY: "treasury"},
    "vix": {GRANULARITY_MINUTE: "yahoo", GRANULARITY_DAILY: "cboe"},
}
