"""美股代理行情源：正常交易时段美股（代币化美股）的主行情源。

上游是公开的第三方代理行情（走势接口），来源标识记在 `candles.source` 的
`us_equity_proxy` 上。它实现与 OKX 相同的 `MarketDataPort`，业务层按来源取数，
不需要知道上游是交易所还是代理。

能力声明：只提供日线
--------------------

上游本身还能给日内线（1 小时约 730 天，5 分钟与 15 分钟约 60 天），本系统仍然只
声明日线，原因有两条：

- Q5 / D3 把代理数据定义为「真实美股日线」，一次回测只允许单一数据源；
- 缺口检测对非日线周期按固定步长排网格（`app/market/candles.py` 的
  `expected_open_times`），而美股日内只有 6.5 小时在交易。声明日内周期会让完全
  正确的行情被判出每天约 17.5 根的假缺口。

因此 `supported_timeframes()` 只返回 `1d`，其余周期在发出任何请求之前就抛
`ValidationError`——T1.7 的来源选择据此判断「这个源在某个周期上能不能用」。

复权口径：只消费上游的复权收盘价（`adj_close`），不自行按分红 / 拆股推算复权因子。
请求带 `events=div,splits`，但事件本身不参与取值；上游若没有下发复权收盘价，按上游
数据不可用处理，因为无法确认收盘价已经复权。

身份口径：`inst_id` 是 OKX 侧的标的标识（如 `XAAPL-USDT`），返回的 K 线也用这个
标识，好让同一标的在库里有两种来源；美股代码由 `ticker_of` 给出，默认实现查标的表
的 `product_key`——配对关系由标的模块维护，本层不拆字符串。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.core import (
    Bar,
    DataUnavailable,
    InstrumentRef,
    MarketDataPort,
    Ticker,
    Timeframe,
    ValidationError,
    register,
)
from app.exchange.errors import ExchangeError
from app.instrument import list_instruments, trading_rules

__all__ = [
    "SOURCE",
    "SUPPORTED_TIMEFRAMES",
    "UsEquityMarketData",
    "create_us_equity_market_data",
    "require_supported_timeframe",
]

# 行情来源标识：与 `app.api.schemas.common.DataSource`、`candles.source` 同值。
SOURCE = "us_equity_proxy"

# 能力声明：只有日线。`supported_timeframes()` 与 `require_supported_timeframe()`
# 成对使用，声明与拒绝不能只有一半。
SUPPORTED_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.parse("1d"),)

_CHART_PATH = "/v8/finance/chart/{ticker}"
_INTERVAL = "1d"
# 复权所需的公司行为：只用来确认复权已生效，不落库、不参与收益计算。
_EVENTS = "div,splits"
# 公开接口对空 `User-Agent` 直接返回 429，必须声明一个浏览器形态的标识。
_USER_AGENT = "Mozilla/5.0 (compatible; trading-us-equity-proxy/1.0)"
_HTTP_OK = 200
_ONE_DAY_SECONDS = 86_400
# 回溯窗口的日历缓冲：一周只有 5 个交易日，再加一周盖住休市日。
_WINDOW_BUFFER_DAYS = 7
_PRICE_FIELDS = ("open", "high", "low", "volume")
# 上游以 JSON 浮点给价（float32 过一遍 float64，小数位 13-14 位）。原样写成
# `Decimal` 会带着二进制噪声入库，超过契约 `DecimalString` 的 12 位上限，K 线接口
# 序列化时直接 500。价格收敛到 4 位小数：美股最小报价单位是分，低于 1 美元的标的
# 最细到 4 位，再多的位只是噪声；成交量按整数股收敛。
_PRICE_QUANTUM = Decimal("0.0001")
_VOLUME_QUANTUM = Decimal(1)


@register("provider", SOURCE)
def create_us_equity_market_data(
    *,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
    ticker_of: Callable[[str], str] | None = None,
) -> UsEquityMarketData:
    """按进程配置装配美股代理行情源。

    `transport` 供测试注入假行情，注入后不会发起真实网络请求；`ticker_of` 供测试
    注入固定映射，默认查标的表。
    """

    return UsEquityMarketData(settings=settings, transport=transport, ticker_of=ticker_of)


class UsEquityMarketData(MarketDataPort):
    """美股代理行情的端口实现：只做历史日线，不做标的元数据与实时快照。

    装配入口是 `create_us_equity_market_data`（登记在 `app.core.registry` 的
    `provider` 桶里）；登记发生在 import 期，不做目录扫描。
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        ticker_of: Callable[[str], str] | None = None,
    ) -> None:
        active = settings or get_settings()
        self._ticker_of = ticker_of or _ticker_from_instrument
        # 交易所标识 → 美股代码：一次同步要翻十几到几十页，同一标的的配对关系不必
        # 每页都查一次标的表。只缓存查到的结果，新标的仍然下一次就被发现。
        self._tickers: dict[str, str] = {}
        self._client = httpx.Client(
            base_url=active.us_equity_rest_base_url,
            timeout=active.us_equity_http_timeout_seconds,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    # ------------------------------------------------------------ 能力声明

    def supported_timeframes(self) -> tuple[Timeframe, ...]:
        """本来源能提供的周期：只有日线（理由见模块 docstring）。"""

        return SUPPORTED_TIMEFRAMES

    # ------------------------------------------------------------ 端口方法

    def instruments(self, inst_type: str) -> list[InstrumentRef]:
        """代理标的不进入可交易集合：不下发标的元数据，也不写标的表。"""

        raise DataUnavailable("美股代理行情源不下发标的元数据; 代理标的不进入可交易集合")

    def candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        limit: int = 100,
    ) -> list[Bar]:
        """最近 `limit` 根已完成的日线；与 `history_candles` 同一口径。"""

        return self.history_candles(inst_id, timeframe, inst_type=inst_type, limit=limit)

    def history_candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        """历史日线（升序）；`after` 是分页游标，取更早的一段。"""

        require_supported_timeframe(timeframe)
        # 类别词表由标的模块维护：未登记的类别在这里就报错，不退回另一类口径。
        trading_rules(inst_type)
        if limit < 1:
            raise ValidationError(f"limit 必须为正:{limit}")
        if after is not None and after.tzinfo is None:
            raise ValidationError("分页游标必须带时区")

        ticker = self._resolve_ticker(inst_id)
        period2 = (
            int(after.timestamp()) if after is not None else int(datetime.now(UTC).timestamp())
        )
        period1 = period2 - (limit * 2 + _WINDOW_BUFFER_DAYS) * _ONE_DAY_SECONDS
        result = self._fetch(ticker, period1=period1, period2=period2)

        bars = _parse_bars(inst_id, timeframe, result)
        if after is not None:
            bars = [bar for bar in bars if bar.open_time < after]
        return bars[-limit:]

    def ticker(self, inst_id: str, *, inst_type: str) -> Ticker:
        """不实现实时行情：要快照就明说，不拿最后一根收盘价冒充。"""

        raise DataUnavailable("美股代理行情源不提供实时行情; 只提供历史日线")

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------ 内部

    def _resolve_ticker(self, inst_id: str) -> str:
        cached = self._tickers.get(inst_id)
        if cached is not None:
            return cached
        ticker = self._ticker_of(inst_id).strip().upper()
        if not ticker:
            raise ValidationError(f"标的 {inst_id} 没有对应的美股代码, 不能取代理行情")
        self._tickers[inst_id] = ticker
        return ticker

    def _fetch(self, ticker: str, *, period1: int, period2: int) -> dict[str, Any]:
        params = {
            "period1": str(period1),
            "period2": str(period2),
            "interval": _INTERVAL,
            "events": _EVENTS,
            "includeAdjustedClose": "true",
        }
        try:
            response = self._client.get(_CHART_PATH.format(ticker=ticker), params=params)
        except httpx.HTTPError as exc:
            raise ExchangeError(f"美股代理行情请求失败:{exc}") from exc
        if response.status_code != _HTTP_OK:
            raise ExchangeError(
                f"美股代理行情返回 HTTP {response.status_code}",
                code=str(response.status_code),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExchangeError("美股代理行情返回了非 JSON 应答") from exc
        return _result_of(payload)


def require_supported_timeframe(timeframe: Timeframe) -> None:
    """不在能力声明里的周期直接拒绝：先校验，再谈要不要发请求。"""

    if timeframe in SUPPORTED_TIMEFRAMES:
        return
    supported = ", ".join(bar.value for bar in SUPPORTED_TIMEFRAMES)
    raise ValidationError(
        f"美股代理行情源只提供 {supported}, 不支持 {timeframe.value}; 日内周期请改用 OKX 行情"
    )


def _result_of(payload: Any) -> dict[str, Any]:
    """从应答里取出 `chart.result[0]`；上游报错与空结果都收敛成 `ExchangeError`。"""

    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise ExchangeError("美股代理行情应答缺少 chart 字段")
    error = chart.get("error")
    if isinstance(error, dict) and error:
        description = str(error.get("description") or "美股代理行情上游报错")
        code = error.get("code")
        raise ExchangeError(description, code=None if code is None else str(code))
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise ExchangeError("美股代理行情没有返回数据")
    result = results[0]
    if not isinstance(result, dict):
        raise ExchangeError("美股代理行情应答的 result 形状不认识")
    return result


def _first_entry(indicators: dict[str, Any], key: str) -> dict[str, Any]:
    """`indicators.<key>` 是单元素列表：取第一项，并要求它确实是字典。"""

    entries = indicators.get(key)
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        raise ExchangeError(f"美股代理行情应答的 indicators.{key} 形状不认识")
    return entries[0]


def _parse_bars(inst_id: str, timeframe: Timeframe, result: dict[str, Any]) -> list[Bar]:
    """应答 → 中立 `Bar`：收盘价取复权列，空值行跳过而不是补造。

    应答形状不对一律按上游故障处理（`ExchangeError`），与本模块其他解析路径一致；
    窗口里确实没有行情时返回空列表——翻页到尽头靠这个信号结束，不能当成故障。
    """

    timestamps = result.get("timestamp")
    if not isinstance(timestamps, list):
        raise ExchangeError("美股代理行情应答缺少 timestamp")
    if not timestamps:
        return []

    indicators = result.get("indicators")
    if not isinstance(indicators, dict):
        raise ExchangeError("美股代理行情应答缺少 indicators")
    quote = _first_entry(indicators, "quote")
    adjusted = _first_entry(indicators, "adjclose").get("adjclose")
    if not isinstance(adjusted, list):
        raise ExchangeError("美股代理行情没有下发复权收盘价, 无法确认复权口径")
    if len(adjusted) != len(timestamps):
        raise ExchangeError("美股代理行情的复权收盘价与时间戳数量不一致")
    columns: dict[str, list[Any]] = {
        name: quote.get(name) or [] for name in (*_PRICE_FIELDS, "close")
    }
    if any(
        not isinstance(values, list) or len(values) != len(timestamps)
        for values in columns.values()
    ):
        raise ExchangeError("美股代理行情的价格列与时间戳数量不一致")

    session_start, session_end, last_trade = _trading_period(result.get("meta") or {})
    bars: list[Bar] = []
    for index, seconds in enumerate(timestamps):
        values = [columns[name][index] for name in _PRICE_FIELDS]
        close = adjusted[index]
        if close is None or any(value is None for value in values):
            # 上游对停牌等情况会给空值：跳过这一根，不用占位价补造。
            continue
        open_, high, low = (_price(value) for value in values[:3])
        volume = _volume(values[3])
        bars.append(
            Bar(
                inst_id=inst_id,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(int(seconds), tz=UTC),
                open=open_,
                high=high,
                low=low,
                close=_price(close),
                volume=volume,
                # 落在当前时段内、且离时段结束还有距离的那一根尚未收盘：写入路径
                # 会丢掉落库前的未收盘 K 线，等上游补齐后下一轮同步再写进来。
                confirm=not (int(seconds) >= session_start and last_trade < session_end),
                source=SOURCE,
            )
        )
    bars.sort(key=lambda bar: bar.open_time)
    return bars


def _trading_period(meta: dict[str, Any]) -> tuple[int, int, int]:
    """当前常规时段与最近成交时刻（epoch 秒）；缺字段就无法判断收盘，按上游故障处理。"""

    try:
        regular = meta["currentTradingPeriod"]["regular"]
        return int(regular["start"]), int(regular["end"]), int(meta["regularMarketTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExchangeError("美股代理行情没有下发交易时段, 无法判断最后一根是否已收盘") from exc


def _price(value: float | int | str) -> Decimal:
    """上游浮点价 → 价格精度：去掉二进制噪声，不假装比 4 位小数更精确。"""

    return Decimal(str(value)).quantize(_PRICE_QUANTUM)


def _volume(value: float | int | str) -> Decimal:
    """成交量按整数股收敛：上游给的是 float，但股数本身是整数。"""

    return Decimal(str(value)).quantize(_VOLUME_QUANTUM)


def _ticker_from_instrument(inst_id: str) -> str:
    """交易所标识 → 美股代码：配对关系由标的模块维护（`product_key`）。"""

    for row in list_instruments():
        if row.symbol == inst_id:
            return row.product_key
    raise ValidationError(f"未找到标的 {inst_id}, 无法确定对应的美股代码")
