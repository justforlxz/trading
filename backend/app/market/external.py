"""外部市场 Provider 适配、五个市场指标与外部数据集同步。

页面和 API 只认统一的 `MarketOverviewProvider`，不绑定任何供应商的字段名。供应商
未确认时本模块不内置真实实现：调用方按名字注入实现，没有实现就如实返回「未配置」，
不用旧值或演示值冒充实时数据。

市场概览固定五个指标：NASDAQ、SP500、DOW、VIX 来自外部 Provider，BTC 来自 OKX
公开行情。Provider 超时、限流或字段缺失时，对应指标返回 `quality_status` 与最后
成功时间，顶层 `stale` 为真；不把上一次的数值继续当作当前值。

外部数据集同步写 `data_sync_jobs`，健康接口只读任务表，不在请求里临时探测上游。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.core import Clock, SystemClock, UpstreamError, ValidationError, utc_from_millis
from app.exchange import ExchangeError, OkxClient
from app.market import sync_jobs
from app.market.events import EventInput, NewsInput, upsert_market_events, upsert_news
from app.market.session import SESSION_REGULAR, asset_session

__all__ = [
    "MARKET_QUOTE_STALE_AFTER",
    "MARKET_SYMBOLS",
    "SYMBOL_NAMES",
    "MarketOverview",
    "MarketOverviewItem",
    "MarketOverviewProvider",
    "MarketOverviewService",
    "ProviderPayloadError",
    "ProviderQuote",
    "ProviderRateLimited",
    "ProviderTimeout",
    "get_provider",
    "provider_names",
    "register_provider",
    "sync_external_dataset",
]

MARKET_SYMBOLS: tuple[str, ...] = ("NASDAQ", "SP500", "DOW", "VIX", "BTC")
SYMBOL_NAMES: dict[str, str] = {
    "NASDAQ": "NASDAQ Composite",
    "SP500": "S&P 500",
    "DOW": "Dow Jones Industrial Average",
    "VIX": "CBOE Volatility Index",
    "BTC": "Bitcoin",
}
QUALITY = ("normal", "missing", "delayed", "abnormal", "pending")
EXTERNAL_SYMBOLS = ("NASDAQ", "SP500", "DOW", "VIX")
DATASETS = ("market_overview", "market_events", "news")
BTC_INST_ID = "BTC-USDT"
BTC_SOURCE = "okx_spot"
# 报价时间超过该阈值即视为过期：同步任务刚结束也不能把旧报价当成当前值。
MARKET_QUOTE_STALE_AFTER = timedelta(hours=24)


class ProviderError(UpstreamError):
    """外部 Provider 的可预期失败。"""


class ProviderTimeout(ProviderError):
    """Provider 超时。"""


class ProviderRateLimited(ProviderError):
    """Provider 限流。"""


class ProviderPayloadError(ProviderError):
    """Provider 返回了缺字段或无法理解的数据。"""


@dataclass(frozen=True, slots=True)
class ProviderQuote:
    """一个市场指标的供应商无关表示；数值缺失时 `value` 为 `None`。"""

    symbol: str
    value: Decimal
    change: Decimal | None = None
    change_pct: Decimal | None = None
    as_of: datetime | None = None
    is_delayed: bool = False
    market_session: str | None = None
    source_url: str | None = None


class MarketOverviewProvider(Protocol):
    """外部市场数据适配器：页面与 API 只依赖这四个方法与统一结构。"""

    name: str

    def overview(self) -> Sequence[ProviderQuote]:
        """五个指标里的四个外部指数；不要求返回 BTC。"""

        raise NotImplementedError

    def events(self, *, start: datetime, end: datetime) -> Sequence[EventInput]:
        """宏观/公司事件。"""

        raise NotImplementedError

    def news(self, *, tickers: Sequence[str], limit: int) -> Sequence[NewsInput]:
        """按标的筛选新闻。`tickers` 为空表示最近新闻。"""

        raise NotImplementedError


_PROVIDERS: dict[str, Callable[[], MarketOverviewProvider]] = {}


def register_provider(
    name: str,
    factory: Callable[[], MarketOverviewProvider],
    *,
    replace: bool = False,
) -> None:
    """登记一个 Provider 实现；测试注入与后续真实供应商都走这里。"""

    key = name.strip()
    if not key:
        raise ValidationError("Provider 名字不能为空")
    if not callable(factory):
        raise ValidationError("Provider factory 必须是可调用对象")
    if key in _PROVIDERS and not replace:
        raise ValidationError(f"Provider 已登记: {key}")
    _PROVIDERS[key] = factory


def provider_names() -> tuple[str, ...]:
    """已登记的 Provider 名字，按字典序。"""

    return tuple(sorted(_PROVIDERS))


def get_provider(name: str | None) -> MarketOverviewProvider | None:
    """按名字构造 Provider；未配置返回 `None`，登记名不存在按调用方错误处理。"""

    key = (name or "").strip()
    if not key:
        return None
    factory = _PROVIDERS.get(key)
    if factory is None:
        available = ", ".join(provider_names()) or "(空)"
        raise ValidationError(f"未登记的 Provider: {key}; 已登记: {available}")
    return factory()


@dataclass(frozen=True, slots=True)
class MarketOverviewItem:
    symbol: str
    name: str
    value: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    market_session: str
    source: str
    as_of: datetime | None
    is_delayed: bool
    quality_status: str
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class MarketOverview:
    as_of: datetime
    provider: str | None
    stale: bool
    stale_reason: str | None
    last_success_at: datetime | None
    items: tuple[MarketOverviewItem, ...]


def _unavailable_item(
    symbol: str,
    *,
    source: str,
    session: str,
) -> MarketOverviewItem:
    return MarketOverviewItem(
        symbol=symbol,
        name=SYMBOL_NAMES[symbol],
        value=None,
        change=None,
        change_pct=None,
        market_session=session,
        source=source,
        as_of=None,
        is_delayed=False,
        quality_status="missing",
        source_url=None,
    )


def _decorate_external(
    quote: ProviderQuote,
    *,
    source: str,
    now: datetime,
) -> MarketOverviewItem:
    if quote.symbol not in MARKET_SYMBOLS:
        raise ProviderPayloadError(f"Provider 返回了未知指标 {quote.symbol!r}")
    if quote.as_of is None:
        raise ProviderPayloadError(f"{quote.symbol} 缺少 as_of")
    try:
        value = Decimal(str(quote.value))
    except (InvalidOperation, ValueError) as exc:
        raise ProviderPayloadError(f"{quote.symbol} 的 value 不是十进制数") from exc
    session = quote.market_session or asset_session("tokenized_equity", now)
    if now - quote.as_of > MARKET_QUOTE_STALE_AFTER:
        quality = "stale"
    elif quote.is_delayed:
        quality = "delayed"
    else:
        quality = "normal"
    return MarketOverviewItem(
        symbol=quote.symbol,
        name=SYMBOL_NAMES[quote.symbol],
        value=value,
        change=quote.change,
        change_pct=quote.change_pct,
        market_session=session,
        source=source,
        as_of=quote.as_of,
        is_delayed=quote.is_delayed,
        quality_status=quality,
        source_url=quote.source_url,
    )


def _load_okx_btc() -> ProviderQuote:
    """BTC 现价与 24 小时涨跌，直接取 OKX 公共 ticker。"""

    with OkxClient() as client:
        rows = client.get("/api/v5/market/ticker", {"instId": BTC_INST_ID})
    if not rows or not isinstance(rows[0], dict):
        raise ProviderPayloadError("OKX BTC ticker 为空")
    row = rows[0]
    try:
        last = Decimal(str(row["last"]))
        open_24h = Decimal(str(row["open24h"]))
        moment = utc_from_millis(row["ts"])
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ProviderPayloadError(f"OKX BTC ticker 缺字段: {exc}") from exc
    change = last - open_24h
    change_pct = None if open_24h == 0 else (change / open_24h * 100).quantize(Decimal("0.01"))
    return ProviderQuote(
        symbol="BTC",
        value=last,
        change=change,
        change_pct=change_pct,
        as_of=moment,
        is_delayed=False,
        market_session=SESSION_REGULAR,
        source_url=None,
    )


class MarketOverviewService:
    """把外部 Provider 与 OKX BTC 合成固定的五个指标。"""

    def __init__(
        self,
        *,
        provider: MarketOverviewProvider | None = None,
        btc_loader: Callable[[], ProviderQuote] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._provider = provider
        self._btc_loader = btc_loader or _load_okx_btc
        self._clock = clock or SystemClock()

    def overview(self) -> MarketOverview:
        now = self._clock.now()
        provider = self._provider
        provider_name = None if provider is None else provider.name
        last_success = (
            None
            if provider_name is None
            else sync_jobs.latest_success_at(provider=provider_name, dataset="market_overview")
        )
        external: dict[str, MarketOverviewItem] = {}
        stale_reason: str | None = None
        session = asset_session("tokenized_equity", now)

        if provider is None:
            stale_reason = "外部行情 Provider 未配置"
            for symbol in EXTERNAL_SYMBOLS:
                external[symbol] = _unavailable_item(symbol, source="unconfigured", session=session)
        else:
            try:
                quotes = provider.overview()
            except ProviderTimeout:
                stale_reason = "外部行情 Provider 超时"
            except ProviderRateLimited:
                stale_reason = "外部行情 Provider 限流"
            except ProviderPayloadError as exc:
                stale_reason = f"外部行情 Provider 返回字段不完整: {exc}"
            except ProviderError as exc:
                stale_reason = str(exc)
            else:
                try:
                    for quote in quotes:
                        if quote.symbol in EXTERNAL_SYMBOLS:
                            external[quote.symbol] = _decorate_external(
                                quote, source=provider.name, now=now
                            )
                except ProviderPayloadError as exc:
                    stale_reason = f"外部行情 Provider 返回字段不完整: {exc}"
                missing = [symbol for symbol in EXTERNAL_SYMBOLS if symbol not in external]
                if missing:
                    stale_reason = stale_reason or f"外部行情缺少指标: {', '.join(missing)}"
                    for symbol in missing:
                        external[symbol] = _unavailable_item(
                            symbol, source=provider.name, session=session
                        )

        if stale_reason is not None:
            for symbol in EXTERNAL_SYMBOLS:
                external.setdefault(
                    symbol,
                    _unavailable_item(
                        symbol,
                        source=provider_name or "unconfigured",
                        session=session,
                    ),
                )

        try:
            btc = self._btc_loader()
            btc_item = _decorate_external(btc, source=BTC_SOURCE, now=now)
        except ProviderTimeout:
            btc_item = _unavailable_item("BTC", source=BTC_SOURCE, session=SESSION_REGULAR)
            stale_reason = stale_reason or "OKX BTC 行情超时"
        except ProviderPayloadError as exc:
            btc_item = _unavailable_item("BTC", source=BTC_SOURCE, session=SESSION_REGULAR)
            stale_reason = stale_reason or f"OKX BTC 行情字段缺失: {exc}"
        except (ExchangeError, UpstreamError) as exc:
            btc_item = _unavailable_item("BTC", source=BTC_SOURCE, session=SESSION_REGULAR)
            stale_reason = stale_reason or f"OKX BTC 行情不可用: {exc}"

        items = (*tuple(external[symbol] for symbol in EXTERNAL_SYMBOLS), btc_item)
        stale_symbols = [item.symbol for item in items if item.quality_status == "stale"]
        if stale_symbols and stale_reason is None:
            stale_reason = f"外部行情数据已过期: {', '.join(stale_symbols)}"
        stale = any(item.quality_status != "normal" for item in items)
        return MarketOverview(
            as_of=now,
            provider=provider_name,
            stale=stale,
            stale_reason=stale_reason if stale else None,
            last_success_at=last_success,
            items=items,
        )


def sync_external_dataset(
    provider: MarketOverviewProvider,
    dataset: str,
    *,
    instrument_ids: Sequence[str] = (),
    clock: Clock | None = None,
) -> sync_jobs.SyncJobView:
    """执行一次外部数据集同步并写任务流水；失败保留错误后继续抛出。"""

    if dataset not in DATASETS:
        raise ValidationError(f"未知数据集 {dataset!r}; 支持: {', '.join(DATASETS)}")
    moment = (clock or SystemClock()).now()
    job = sync_jobs.start_sync_job(provider.name, dataset, clock=clock)
    data_as_of: datetime | None = None
    try:
        if dataset == "market_overview":
            quotes = provider.overview()
            rows = len(quotes)
            moments = [quote.as_of for quote in quotes if quote.as_of is not None]
            data_as_of = min(moments) if moments else None
        elif dataset == "market_events":
            events_rows = provider.events(
                start=moment - timedelta(days=30), end=moment + timedelta(days=90)
            )
            rows = upsert_market_events(
                replace(item, source=item.source or provider.name) for item in events_rows
            )
        else:
            news_rows = provider.news(tickers=tuple(instrument_ids), limit=100)
            rows = upsert_news(
                replace(item, source=item.source or provider.name) for item in news_rows
            )
    except ProviderError as exc:
        sync_jobs.finish_sync_job(job.id, "failed", error=str(exc), clock=clock)
        raise
    except Exception as exc:
        # 非预期异常只记录类型名，不把上游原始应答或连接串写进任务流水。
        sync_jobs.finish_sync_job(job.id, "failed", error=type(exc).__name__, clock=clock)
        raise
    return sync_jobs.finish_sync_job(
        job.id,
        "succeeded",
        rows=rows,
        cursor=None if data_as_of is None else data_as_of.isoformat(),
        clock=clock,
    )
