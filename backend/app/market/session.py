"""交易时段与行情来源优先级：两层时段模型，纯函数。

系统同时看两类市场：美股（有盘前 / 正常 / 盘后与休市日）与加密资产（24/7 连续）。
「现在该用哪个来源的行情」不是「开市 / 休市」二选一，而是「资产时段 × 资产类别」
查表——代币化股票在正常时段取美股代理行情，休市时段仍取 OKX 合约行情；加密资产
任何时候都取 OKX 行情。

时段按**标的所属资产**判，不按标的类别判：`SWAP` 里既有代币化股票永续
（`AAPL-USDT-SWAP`，受美股时段影响）也有加密永续（`BTC-USDT-SWAP`，全天连续）。
类别规则的 `session_kind` 只在 `asset_type` 缺失时兜底。

24/7 资产在四个资产时段里恒为 `regular`：它们没有盘前盘后，也不休市，`regular`
是唯一表示「正在交易的常规时段」的取值。

休市日表按年硬编码在本文件一处。表里没有的年份直接报错，而不是当成「没有假期」——
漏一年的假期会静默把休市日判成交易中，比拒绝服务危险得多。提前收盘的半日市不在
本模型内（它们只影响收盘时刻，不影响「哪一天交易」）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core import ValidationError
from app.instrument import trading_rules

__all__ = [
    "COMMODITY_TOKEN",
    "CRYPTO",
    "EXCHANGE_CLOSED",
    "EXCHANGE_OPEN",
    "SESSION_CLOSED",
    "SESSION_POST",
    "SESSION_PRE",
    "SESSION_REGULAR",
    "TOKENIZED_EQUITY",
    "UNKNOWN_ASSET",
    "asset_session",
    "daily_open_time",
    "day_asset_type",
    "exchange_session",
    "is_trading_day",
    "next_daily_open_time",
    "primary_source",
]

# 资产类别：与 `app.instrument.model` 的落库取值一致。
CRYPTO = "crypto"
TOKENIZED_EQUITY = "tokenized_equity"
COMMODITY_TOKEN = "commodity_token"
UNKNOWN_ASSET = "unknown"

# 资产时段取值。
SESSION_PRE = "pre"
SESSION_REGULAR = "regular"
SESSION_POST = "post"
SESSION_CLOSED = "closed"
_SESSIONS = frozenset({SESSION_PRE, SESSION_REGULAR, SESSION_POST, SESSION_CLOSED})

# 交易所时段取值。
EXCHANGE_OPEN = "open"
EXCHANGE_CLOSED = "closed"

# 时段类别的两个取值：与 `app.instrument.rules.TradingRules.session_kind` 同值。
_KIND_CRYPTO = "crypto_24_7"
_KIND_EQUITY = "equity"

# OKX 的日线以 UTC+8 零点为零点（= 16:00 UTC）；24/7 市场没有别的开盘时刻可用。
UTC8 = timezone(timedelta(hours=8))

# 美股（NYSE）时段的本地时刻：盘前 04:00、正常 09:30–16:00、盘后至 20:00。
EASTERN = ZoneInfo("America/New_York")
PRE_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
POST_CLOSE = time(20, 0)

# 行情来源标识：与 `app.api.schemas.common.DataSource` 同值。
SOURCE_EQUITY_PROXY = "us_equity_proxy"
SOURCE_OKX = "okx"

# 资产的时段类别：代币化商品与未登记分类暂按代币化股票处理（临时取值，接入真实
# 商品行情时再定；`unknown` 同理）。
_ASSET_KINDS: dict[str, str] = {
    CRYPTO: _KIND_CRYPTO,
    TOKENIZED_EQUITY: _KIND_EQUITY,
    COMMODITY_TOKEN: _KIND_EQUITY,
    UNKNOWN_ASSET: _KIND_EQUITY,
}

# 交易所全休市日（NYSE），按年硬编码。
_HOLIDAYS: dict[int, frozenset[date]] = {
    2025: frozenset(
        {
            date(2025, 1, 1),  # 元旦
            date(2025, 1, 9),  # 全国哀悼日（卡特）
            date(2025, 1, 20),  # 马丁·路德·金纪念日
            date(2025, 2, 17),  # 华盛顿诞辰
            date(2025, 4, 18),  # 耶稣受难日
            date(2025, 5, 26),  # 阵亡将士纪念日
            date(2025, 6, 19),  # 六月节
            date(2025, 7, 4),  # 独立日
            date(2025, 9, 1),  # 劳动节
            date(2025, 11, 27),  # 感恩节
            date(2025, 12, 25),  # 圣诞节
        }
    ),
    2026: frozenset(
        {
            date(2026, 1, 1),
            date(2026, 1, 19),
            date(2026, 2, 16),
            date(2026, 4, 3),
            date(2026, 5, 25),
            date(2026, 6, 19),
            date(2026, 7, 3),  # 独立日观察日（7/4 是周六）
            date(2026, 9, 7),
            date(2026, 11, 26),  # 感恩节
            date(2026, 12, 25),
        }
    ),
    2027: frozenset(
        {
            date(2027, 1, 1),
            date(2027, 1, 18),
            date(2027, 2, 15),
            date(2027, 3, 26),
            date(2027, 5, 31),
            date(2027, 6, 18),  # 六月节观察日（6/19 是周六）
            date(2027, 7, 5),  # 独立日观察日（7/4 是周日）
            date(2027, 9, 6),
            date(2027, 11, 25),
            date(2027, 12, 24),  # 圣诞观察日（12/25 是周六）
        }
    ),
}

_ONE_DAY = timedelta(days=1)


def asset_session(asset_type: str, ts: datetime, *, inst_type: str | None = None) -> str:
    """某一时刻资产的交易时段：`pre` / `regular` / `post` / `closed`。

    `asset_type` 是首要依据；它为空时用 `inst_type` 的类别规则兜底（`SWAP` 一律给
    `equity`，是粗粒度默认值，不能代替资产类型）。
    """

    if _session_kind(asset_type, inst_type) == _KIND_CRYPTO:
        return SESSION_REGULAR
    return _equity_session(_require_aware(ts))


def exchange_session(ts: datetime) -> str:
    """交易所时段：正常交易时段内为 `open`，其余（含盘前盘后与休市日）为 `closed`。"""

    is_open = _equity_session(_require_aware(ts)) == SESSION_REGULAR
    return EXCHANGE_OPEN if is_open else EXCHANGE_CLOSED


def primary_source(session: str, asset_type: str, inst_type: str) -> str:
    """「资产时段 × 资产类别」→ 该时刻的参考行情来源。

    代币化股票在盘前、正常、盘后都取美股代理行情（盘前盘后用它的最新收盘价作参考
    价，跨源价差由 `divergence` 报）；休市时段与加密资产取 OKX 行情，来源按形态
    区分现货与永续——现货与永续是两行行情，混用一个来源会取错价格。
    """

    if session not in _SESSIONS:
        raise ValidationError(f"未知的资产时段 {session!r}; 支持: {', '.join(sorted(_SESSIONS))}")
    if _session_kind(asset_type, inst_type) == _KIND_CRYPTO or session == SESSION_CLOSED:
        return _okx_source(inst_type)
    return SOURCE_EQUITY_PROXY


def daily_open_time(asset_type: str, ts: datetime, *, inst_type: str | None = None) -> datetime:
    """`ts` 所在（或其之前最近的）交易日的日线开盘时刻，即日线的定界。

    代币化股票按当日正常时段开盘（美东 09:30）定界；24/7 资产没有自己的开盘，
    沿用 OKX 的 UTC+8 零点（16:00 UTC）定界。两边都不是「自然日 00:00」。
    """

    moment = _require_aware(ts)
    if _session_kind(asset_type, inst_type) == _KIND_CRYPTO:
        local = moment.astimezone(UTC8).replace(hour=0, minute=0, second=0, microsecond=0)
        return local.astimezone(UTC)
    day = _trading_day_at_or_before(moment)
    return _regular_open(day)


def next_daily_open_time(
    asset_type: str, after: datetime, *, inst_type: str | None = None
) -> datetime:
    """`after` 之后的下一个日线开盘时刻。

    24/7 资产每 24 小时一根，直接加一天；美股只在交易日产生日线，跳过周末与休市日。
    """

    moment = _require_aware(after)
    if _session_kind(asset_type, inst_type) == _KIND_CRYPTO:
        return moment + _ONE_DAY
    day = moment.astimezone(EASTERN).date() + _ONE_DAY
    while not is_trading_day(day):
        day += _ONE_DAY
    return _regular_open(day)


def day_asset_type(asset_type: str, source: str | None = None) -> str:
    """一条行情按哪个市场的日界定界。

    OKX 的日线是交易所自己的交易日（UTC+8 零点），与标的所属资产的美股时段不是同一天：
    `AAPL-USDT-SWAP` 的 OKX 日线从 16:00 UTC 开始，而它的美股交易日从 09:30 美东开始。
    把两者混用会让完全正确的行情被判成有缺口，因此日界跟着来源所属市场走，而资产时段
    只负责回答「这一刻该看哪个来源」。

    `source` 为空表示调用方还没有来源信息（同步时按标的资产本身定界）。
    """

    if source is not None and (source == SOURCE_OKX or source.startswith(f"{SOURCE_OKX}_")):
        return CRYPTO
    return asset_type


def is_trading_day(day: date) -> bool:
    """该日交易所是否开市：工作日且不在休市日表里。"""

    return day.weekday() < 5 and day not in _holidays(day.year)


def _session_kind(asset_type: str, inst_type: str | None) -> str:
    """资产类别 → 时段类别；资产类别缺失时用标的类别的规则兜底。"""

    name = asset_type.strip().lower()
    if name:
        kind = _ASSET_KINDS.get(name)
        if kind is None:
            supported = ", ".join(sorted(_ASSET_KINDS))
            raise ValidationError(f"未知的资产类别 {name!r}; 支持: {supported}")
        return kind
    if inst_type is None:
        raise ValidationError("资产类别与标的类别都为空, 无法判定交易时段")
    return trading_rules(inst_type).session_kind


def _equity_session(moment: datetime) -> str:
    local = moment.astimezone(EASTERN)
    if not is_trading_day(local.date()):
        return SESSION_CLOSED
    clock = local.time()
    if clock < PRE_OPEN:
        return SESSION_CLOSED
    if clock < REGULAR_OPEN:
        return SESSION_PRE
    if clock < REGULAR_CLOSE:
        return SESSION_REGULAR
    if clock < POST_CLOSE:
        return SESSION_POST
    return SESSION_CLOSED


def _trading_day_at_or_before(moment: datetime) -> date:
    """`moment` 所属交易日：当日开市且已过开盘时刻算当日，否则往前找最近的开市日。"""

    local = moment.astimezone(EASTERN)
    day = local.date()
    if is_trading_day(day) and local.time() >= REGULAR_OPEN:
        return day
    day -= _ONE_DAY
    while not is_trading_day(day):
        day -= _ONE_DAY
    return day


def _regular_open(day: date) -> datetime:
    """某日正常时段开盘时刻（美东本地时刻按该日时区偏移换算）。"""

    return datetime.combine(day, REGULAR_OPEN, tzinfo=EASTERN)


def _okx_source(inst_type: str) -> str:
    """OKX 一侧的行情来源：按形态取 `okx_spot` / `okx_swap`。"""

    rules = trading_rules(inst_type)
    return f"{SOURCE_OKX}_swap" if rules.has_margin else f"{SOURCE_OKX}_spot"


def _holidays(year: int) -> frozenset[date]:
    known = _HOLIDAYS.get(year)
    if known is None:
        raise ValidationError(f"休市日表没有 {year} 年, 需先在 app/market/session.py 补表")
    return known


def _require_aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValidationError("时段判定需要带时区的时间")
    return ts
