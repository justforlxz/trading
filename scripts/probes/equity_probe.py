#!/usr/bin/env python3
"""真实美股行情探针：免 key、只用标准库，验证 Yahoo chart v8 是否可用。

用法：
    python3 scripts/probes/equity_probe.py chart AAPL 1d 5d
    python3 scripts/probes/equity_probe.py chart SPY 1h 5d

输出交易日/数据点数量与首末收盘价，并标注来源与抓取时间。
取不到数据时打印 `MISSING_SOURCE` 并以退出码 2 结束——**不会**用 OKX 指数
价或任何合成值顶替真实行情（见 `docs/risk/external-dependencies.md` §2.9）。
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) trading-equity-probe/0.1"


def fetch_chart(symbol: str, interval: str, range_: str, timeout: float = 10.0) -> dict:
    query = urllib.parse.urlencode(
        {"range": range_, "interval": interval, "includePrePost": "false"}
    )
    request = urllib.request.Request(
        f"{CHART_URL.format(symbol=symbol)}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="真实美股行情探针（Yahoo chart v8）")
    sub = parser.add_subparsers(dest="command", required=True)
    chart = sub.add_parser("chart", help="抓取 K 线并打印覆盖情况")
    chart.add_argument("symbol", help="股票代码，例如 AAPL")
    chart.add_argument("interval", nargs="?", default="1d", help="K 线周期，默认 1d")
    chart.add_argument("range_", metavar="RANGE", nargs="?", default="5d", help="时间范围，默认 5d")
    args = parser.parse_args(argv)

    fetched_at = datetime.now(tz=UTC).isoformat()
    try:
        payload = fetch_chart(args.symbol, args.interval, args.range_)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        print(f"MISSING_SOURCE: yahoo chart v8 unavailable: {error}", file=sys.stderr)
        return 2

    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        error = (payload.get("chart") or {}).get("error")
        print(f"MISSING_SOURCE: empty chart result ({error})", file=sys.stderr)
        return 2

    entry = result[0]
    timestamps = entry.get("timestamp") or []
    quote = ((entry.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    points = [
        (int(ts), close) for ts, close in zip(timestamps, closes, strict=False) if close is not None
    ]
    if not points:
        print("MISSING_SOURCE: chart has no usable closes", file=sys.stderr)
        return 2

    first_ts, first_close = points[0]
    last_ts, last_close = points[-1]
    meta = entry.get("meta") or {}
    print(f"source=yahoo chart v8 symbol={args.symbol} interval={args.interval} range={args.range_}")
    print(f"fetched_at={fetched_at}")
    print(f"points={len(points)}")
    print(
        "first="
        f"{datetime.fromtimestamp(first_ts, tz=UTC).isoformat()} close={first_close}"
    )
    print(f"last={datetime.fromtimestamp(last_ts, tz=UTC).isoformat()} close={last_close}")
    if meta.get("regularMarketPrice") is not None:
        print(f"regularMarketPrice={meta['regularMarketPrice']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
