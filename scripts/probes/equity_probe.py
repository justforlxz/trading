#!/usr/bin/env python3
"""真实美股行情源探针（只读，无需 API key）。

用途：S1 调研「美股真实行情」可得性，并给出 OKX 合约价与真实股票价的
可比性证据。文档 docs/risk/external-dependencies.md 引用本脚本输出。

用法：
    python3 scripts/probes/equity_probe.py chart AAPL 1d 5d
    python3 scripts/probes/equity_probe.py prepost AAPL
    python3 scripts/probes/equity_probe.py v7-quote AAPL     # 预期失败，记录失败形态
    python3 scripts/probes/equity_probe.py all

说明：
- Yahoo Finance chart v8 是非官方公开端点，无需 key，但**没有 SLA**，
  随时可能变更或封禁。本脚本只用于事实采集与回归对比，不作为运行时依赖的
  唯一证据；是否采用见 docs/risk/external-dependencies.md 的决策项。
- 任何非 200 都按失败原样打印，不重试、不伪造数据。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) trading-probe/1.0"
TIMEOUT = 20


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    elapsed = time.monotonic() - started
    print(f"[{utcnow()}] GET {url} -> HTTP {status} in {elapsed:.2f}s, {len(body)} bytes")
    return status, body


def cmd_chart(symbol: str, interval: str, rng: str) -> None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval={interval}&range={rng}"
    )
    status, body = fetch(url)
    if status != 200:
        print(f"FAILED status={status} body={body[:400]!r}")
        raise SystemExit(2)
    payload = json.loads(body)
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    keep = {
        k: meta.get(k)
        for k in (
            "symbol",
            "currency",
            "exchangeName",
            "instrumentType",
            "exchangeTimezoneName",
            "gmtoffset",
            "regularMarketPrice",
            "regularMarketTime",
            "hasPrePostMarketData",
        )
    }
    print("meta: " + json.dumps(keep, ensure_ascii=False))
    ts = result.get("timestamp") or []
    print(f"points={len(ts)}")
    if ts:
        closes = result["indicators"]["quote"][0].get("close") or []
        print(f"first_ts={ts[0]} last_ts={ts[-1]}")
        print(f"first_close={closes[0]} last_close={closes[-1]}")


def cmd_prepost(symbol: str) -> None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?interval=1m&range=1d&includePrePost=true"
    )
    status, body = fetch(url)
    if status != 200:
        print(f"FAILED status={status} body={body[:400]!r}")
        raise SystemExit(2)
    result = json.loads(body)["chart"]["result"][0]
    meta = result["meta"]
    print("currentTradingPeriod: " + json.dumps(meta.get("currentTradingPeriod"), ensure_ascii=False))
    print("hasPrePostMarketData: " + json.dumps(meta.get("hasPrePostMarketData")))
    print(f"points={len(result.get('timestamp') or [])}")


def cmd_v7_quote(symbol: str) -> None:
    """Yahoo v7 quote 需要 crumb/cookie，本探针用于记录它的失败形态。"""
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
    status, body = fetch(url)
    print(f"status={status} body={body[:300]!r}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "chart":
        cmd_chart(rest[0], rest[1] if len(rest) > 1 else "1d", rest[2] if len(rest) > 2 else "5d")
    elif cmd == "prepost":
        cmd_prepost(rest[0] if rest else "AAPL")
    elif cmd == "v7-quote":
        cmd_v7_quote(rest[0] if rest else "AAPL")
    elif cmd == "all":
        cmd_chart("AAPL", "1d", "5d")
        cmd_prepost("AAPL")
        cmd_v7_quote("AAPL")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
