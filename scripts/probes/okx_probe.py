#!/usr/bin/env python3
"""OKX 公开行情接口探针（只读，无需 API key）。

用途：S1 外部依赖调研的事实采集脚本。文档 docs/risk/external-dependencies.md
中列出的每条结论都可以用本脚本复现。

用法：
    python3 scripts/probes/okx_probe.py all
    python3 scripts/probes/okx_probe.py instruments
    python3 scripts/probes/okx_probe.py ticker AAPL-USDT-SWAP
    python3 scripts/probes/okx_probe.py candles AAPL-USDT-SWAP 1m 5
    python3 scripts/probes/okx_probe.py history-depth AAPL-USDT-SWAP 1D
    python3 scripts/probes/okx_probe.py funding AAPL-USDT-SWAP
    python3 scripts/probes/okx_probe.py rate-limit AAPL-USDT-SWAP 1m 60

约定：
- 只使用 Python 标准库（urllib），不引入项目依赖。
- 每个子命令都打印本次采集的 UTC 时间戳，便于写进文档。
- HTTP 非 200 或 OKX code != "0" 时以非零码退出，绝不静默降级。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

BASE = "https://www.okx.com"
UA = "trading-probe/1.0"
TIMEOUT = 20


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(path: str) -> dict:
    url = BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read()
        status = resp.status
    elapsed = time.monotonic() - started
    payload = json.loads(body)
    print(f"[{utcnow()}] GET {path} -> HTTP {status} in {elapsed:.2f}s, {len(body)} bytes")
    return payload


def expect_ok(payload: dict) -> list:
    if payload.get("code") != "0":
        print(f"ABORT: OKX error code={payload.get('code')} msg={payload.get('msg')}")
        raise SystemExit(2)
    return payload.get("data", [])


def cmd_instruments() -> None:
    payload = get_json("/api/v5/public/instruments?instType=SWAP")
    data = expect_ok(payload)
    print(f"instruments total = {len(data)}")
    dist = Counter(item.get("instCategory") or "<empty>" for item in data)
    # instCategory: 1=Crypto 3=Stocks 4=Commodities 5=Forex 6=Bonds
    for cat, n in sorted(dist.items()):
        print(f"  instCategory={cat!r}: {n}")
    stocks = [i for i in data if i.get("instCategory") == "3"]
    print(f"stock-like instruments = {len(stocks)}")
    for inst_id in ("AAPL-USDT-SWAP", "GOOGL-USDT-SWAP", "SPY-USDT-SWAP"):
        hit = next((i for i in data if i["instId"] == inst_id), None)
        print(f"sample {inst_id}: {json.dumps(hit, ensure_ascii=False)}")
    print("instId list (instCategory=3): " + ",".join(i["instId"] for i in stocks))


def cmd_ticker(inst_id: str) -> None:
    payload = get_json(f"/api/v5/market/ticker?instId={inst_id}")
    for row in expect_ok(payload):
        keep = {k: row.get(k) for k in ("instId", "last", "askPx", "bidPx", "vol24h", "ts", "sodUtc0")}
        print(json.dumps(keep, ensure_ascii=False))


def cmd_candles(inst_id: str, bar: str, limit: str) -> None:
    payload = get_json(f"/api/v5/market/candles?instId={inst_id}&bar={bar}&limit={limit}")
    rows = expect_ok(payload)
    print(f"rows={len(rows)} bar={bar}")
    for row in rows[:5]:
        # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        print(json.dumps({"open_time": row[0], "o": row[1], "h": row[2], "l": row[3], "c": row[4], "vol": row[5], "confirm": row[8]}))


def cmd_history_depth(inst_id: str, bar: str) -> None:
    total = 0
    after = ""
    oldest = None
    newest = None
    for page in range(1, 11):
        path = f"/api/v5/market/history-candles?instId={inst_id}&bar={bar}&limit=100"
        if after:
            path += f"&after={after}"
        rows = expect_ok(get_json(path))
        if not rows:
            print(f"page {page}: 0 rows, stop")
            break
        total += len(rows)
        oldest = rows[-1][0]
        newest = newest or rows[0][0]
        print(f"page {page}: n={len(rows)} newest={rows[0][0]} oldest={rows[-1][0]}")
        after = rows[-1][0]
        time.sleep(0.2)
    print(f"total={total} newest_open_time={newest} oldest_open_time={oldest}")


def cmd_funding(inst_id: str) -> None:
    payload = get_json(f"/api/v5/public/funding-rate?instId={inst_id}")
    for row in expect_ok(payload):
        keep = {k: row.get(k) for k in ("instId", "fundingRate", "fundingTime", "nextFundingTime")}
        print(json.dumps(keep, ensure_ascii=False))


def cmd_rate_limit(inst_id: str, bar: str, count: str) -> None:
    """并发打满接口，统计 200 / 429 / code=50011 的分布，验证限流确实生效。"""
    import concurrent.futures

    def one(_: int):
        url = f"{BASE}/api/v5/market/candles?instId={inst_id}&bar={bar}&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.loads(resp.read())
            if body.get("code") == "0":
                return "200"
            return f"code={body.get('code')}"
        except urllib.error.HTTPError as exc:
            return f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - 探针需要记录任意失败形态
            return f"ERR {type(exc).__name__}"

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(count)) as pool:
        results = list(pool.map(one, range(int(count))))
    elapsed = time.monotonic() - started
    print(f"[{utcnow()}] {count} parallel requests in {elapsed:.2f}s")
    for outcome, n in sorted(Counter(results).items()):
        print(f"  {outcome}: {n}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "instruments":
        cmd_instruments()
    elif cmd == "ticker":
        cmd_ticker(rest[0])
    elif cmd == "candles":
        cmd_candles(rest[0], rest[1] if len(rest) > 1 else "1m", rest[2] if len(rest) > 2 else "5")
    elif cmd == "history-depth":
        cmd_history_depth(rest[0], rest[1] if len(rest) > 1 else "1D")
    elif cmd == "funding":
        cmd_funding(rest[0])
    elif cmd == "rate-limit":
        cmd_rate_limit(rest[0], rest[1] if len(rest) > 1 else "1m", rest[2] if len(rest) > 2 else "40")
    elif cmd == "all":
        cmd_instruments()
        cmd_ticker("AAPL-USDT-SWAP")
        cmd_candles("AAPL-USDT-SWAP", "1m", "5")
        cmd_candles("AAPL-USDT-SWAP", "1D", "5")
        cmd_funding("AAPL-USDT-SWAP")
        cmd_history_depth("AAPL-USDT-SWAP", "1D")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
