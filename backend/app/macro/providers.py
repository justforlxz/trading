"""宏观数据的上游实现。

一个 provider 只做两件事：按配置里的地址把上游取回来、把上游格式解析成 `Observation`。
地址与凭据不在实现里：调用方从 `settings.data_sources.macro.providers` 读出后作为
`options` 传入，所以「换一个源」只要改配置里的 provider 名与地址，抓取代码不动。

三个实现：

- `treasury`：美国财政部官方 CSV，日线结算值（本域只取 2Y / 10Y）。URL 里的 `{year}`
  替换成当前年份——地址留在配置里，但不会每年 1 月 1 日悄悄失效。
- `cboe`：CBOE 官方 `VIX_History.csv`，日线结算值。
- `yahoo`：Yahoo chart API，分钟级（`^TNX` / `^VIX`）。免费源是**延迟行情**，
  `is_delayed` 如实标 `True`，不当实时。

`is_delayed` 由 provider 自己声明：结算值（财政部、CBOE 收盘价）已经定稿，不是延迟
报价；Yahoo 免费源是延迟行情。上游异常或内容无法理解时抛 `UpstreamError`，服务层据此
降级为缓存值——不返回空列表冒充「今天没有数据」，两者对用户是不同的事实。

Yahoo 对本机 Linux Chrome UA 一律回 429，Windows 桌面 UA 才 200（实测），因此 UA 固定
用 Windows 桌面写法。
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core import Observation, ObservationProvider, UpstreamError, get, list_names, register
from app.macro.series import quantize_value
from app.market import settlement_epoch

__all__ = [
    "PROVIDER_KIND",
    "CboeProvider",
    "TreasuryProvider",
    "YahooProvider",
    "build_provider",
    "parse_cboe",
    "parse_treasury",
    "parse_yahoo",
    "provider_names",
    "source_url",
]

PROVIDER_KIND = "macro_provider"
HTTP_TIMEOUT = httpx.Timeout(10.0)
USER_AGENT = (
    "Mozilla"
    "/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_TREASURY_COLUMNS = {"us10y": "10 Yr", "us2y": "2 Yr"}
_CBOE_SERIES = ("vix",)
_YAHOO_SERIES = ("us10y", "vix")


def _since_epoch(since: datetime | None) -> int | None:
    """`since` → epoch 秒；不设下界时给 `None`。"""

    return None if since is None else int(since.timestamp())


def _text_option(options: Mapping[str, Any], key: str) -> str:
    value = options.get(key)
    return value.strip() if isinstance(value, str) else ""


def _url_for(options: Mapping[str, Any], series_id: str) -> str:
    """取某个序列的上游地址：先看 `urls[series_id]`，再退回共用的 `url`。"""

    urls = options.get("urls")
    if isinstance(urls, Mapping):
        value = urls.get(series_id)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _text_option(options, "url")


def _get_text(url: str, client: httpx.Client | None) -> str:
    """取回上游正文；网络错误与非 200 都转成 `UpstreamError`。"""

    if not url:
        raise UpstreamError("宏观数据源未配置上游地址")
    try:
        if client is not None:
            response = client.get(url)
        else:
            with httpx.Client(
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as local:
                response = local.get(url)
    except httpx.HTTPError as exc:
        raise UpstreamError(f"宏观数据上游请求失败: {exc}") from exc
    if response.status_code != 200:
        raise UpstreamError(f"宏观数据上游返回 HTTP {response.status_code}")
    return response.text


def _require(series: Sequence[str], supported: Sequence[str], provider: str) -> None:
    unknown = [item for item in series if item not in supported]
    if unknown:
        raise UpstreamError(f"{provider} 不提供序列 {unknown}; 只提供 {list(supported)}")


def _us_date(value: str | None) -> date | None:
    """`MM/DD/YYYY` → 日期；空串或格式不对时给 `None`，不猜一个日期出来。"""

    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _decimal(value: str | None) -> Decimal | None:
    """上游文本 → `Decimal`；空串表示「这一天没有发布」，不是 0。"""

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


class TreasuryProvider:
    """美国财政部官方 CSV：整条收益率曲线，一行一个交易日（日线结算值）。"""

    name = "treasury"

    def __init__(self, *, options: Mapping[str, Any], client: httpx.Client | None = None) -> None:
        self._options = options
        self._client = client

    def supports(self, series: Sequence[str]) -> bool:
        return all(item in _TREASURY_COLUMNS for item in series)

    def fetch(self, series: Sequence[str], since: datetime | None) -> list[Observation]:
        _require(series, tuple(_TREASURY_COLUMNS), self.name)
        url = _url_for(self._options, series[0]).replace("{year}", str(datetime.now(UTC).year))
        observations = parse_treasury(_get_text(url, self._client), series, provider=self.name)
        return _filter(observations, since)


class CboeProvider:
    """CBOE 官方 VIX 历史 CSV：`DATE,OPEN,HIGH,LOW,CLOSE`，取收盘价（日线结算值）。"""

    name = "cboe"

    def __init__(self, *, options: Mapping[str, Any], client: httpx.Client | None = None) -> None:
        self._options = options
        self._client = client

    def supports(self, series: Sequence[str]) -> bool:
        return all(item in _CBOE_SERIES for item in series)

    def fetch(self, series: Sequence[str], since: datetime | None) -> list[Observation]:
        _require(series, _CBOE_SERIES, self.name)
        url = _url_for(self._options, "vix")
        observations = parse_cboe(_get_text(url, self._client), provider=self.name)
        return _filter(observations, since)


class YahooProvider:
    """Yahoo chart API：分钟级日线数据。免费源是延迟行情，`is_delayed=True`。"""

    name = "yahoo"

    def __init__(self, *, options: Mapping[str, Any], client: httpx.Client | None = None) -> None:
        self._options = options
        self._client = client

    def supports(self, series: Sequence[str]) -> bool:
        return all(item in _YAHOO_SERIES for item in series)

    def fetch(self, series: Sequence[str], since: datetime | None) -> list[Observation]:
        _require(series, _YAHOO_SERIES, self.name)
        observations: list[Observation] = []
        for series_id in series:
            url = _url_for(self._options, series_id)
            observations.extend(
                parse_yahoo(_load_json(_get_text(url, self._client)), series_id, provider=self.name)
            )
        return _filter(observations, since)


def _filter(observations: list[Observation], since: datetime | None) -> list[Observation]:
    """按 `since` 过滤；日更源的历史很长，只交出需要的那一段。"""

    lower = _since_epoch(since)
    if lower is None:
        return observations
    return [item for item in observations if item.ts >= lower]


def _load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"宏观数据上游返回的不是 JSON: {exc}") from exc


def parse_treasury(text: str, series: Sequence[str], *, provider: str) -> list[Observation]:
    """财政部 CSV → 观测值；空单元格跳过，不补 0。"""

    observations: list[Observation] = []
    for row in csv.DictReader(io.StringIO(text)):
        day = _us_date(row.get("Date"))
        if day is None:
            continue
        ts = settlement_epoch(day)
        for series_id in series:
            value = _decimal(row.get(_TREASURY_COLUMNS[series_id]))
            if value is None:
                continue
            observations.append(
                Observation(
                    series_id=series_id,
                    ts=ts,
                    value=quantize_value(series_id, value),
                    provider=provider,
                    is_delayed=False,
                )
            )
    return observations


def parse_cboe(text: str, *, provider: str) -> list[Observation]:
    """CBOE CSV → VIX 收盘价（日线结算值）。"""

    observations: list[Observation] = []
    for row in csv.DictReader(io.StringIO(text)):
        day = _us_date(row.get("DATE"))
        value = _decimal(row.get("CLOSE"))
        if day is None or value is None:
            continue
        observations.append(
            Observation(
                series_id="vix",
                ts=settlement_epoch(day),
                value=quantize_value("vix", value),
                provider=provider,
                is_delayed=False,
            )
        )
    return observations


def parse_yahoo(payload: Any, series_id: str, *, provider: str) -> list[Observation]:
    """Yahoo chart JSON → 分钟级观测值；时间戳按 UTC 折成 epoch 秒。"""

    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise UpstreamError("Yahoo 返回内容缺少 chart 字段")
    if chart.get("error"):
        raise UpstreamError(f"Yahoo 返回错误: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise UpstreamError("Yahoo 没有返回行情")
    result = results[0] if isinstance(results[0], dict) else {}
    stamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") or []
    closes = (quotes[0] if quotes else {}).get("close") or []
    observations: list[Observation] = []
    for stamp, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        observations.append(
            Observation(
                series_id=series_id,
                ts=int(stamp),
                # Yahoo 的分钟收盘价是二进制浮点（4.911999702453613），按序列精度取整后
                # 再入库，避免把浮点尾巴带到库和首页。
                value=quantize_value(series_id, Decimal(str(close))),
                provider=provider,
                is_delayed=True,
            )
        )
    return observations


register(PROVIDER_KIND, "treasury")(TreasuryProvider)
register(PROVIDER_KIND, "cboe")(CboeProvider)
register(PROVIDER_KIND, "yahoo")(YahooProvider)


def source_url(options: Mapping[str, Any], series_id: str) -> str:
    """该序列在当前 provider 下的上游地址；接口把它作为该行的来源链接返回。"""

    return _url_for(options, series_id)


def provider_names() -> list[str]:
    """已登记的宏观 provider 名；配置校验用它列出可选值。"""

    return list_names(PROVIDER_KIND)


def build_provider(
    name: str,
    *,
    options: Mapping[str, Any],
    client: httpx.Client | None = None,
) -> ObservationProvider:
    """按名字构造 provider；名字未登记时 `app.core.get` 抛参数不合法。"""

    factory = get(PROVIDER_KIND, name)
    return factory(options=options, client=client)
