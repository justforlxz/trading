"""量 `/api/dashboard/summary` 一次请求的 SQL 条数与延迟。

改前改后用同一份脚本、同一份库数据量，数字才有可比性。计数器挂在 SQLAlchemy 的
`before_cursor_execute` 上，只统计请求处理期间真正发到库里的语句；预热请求不计入。

用法（仓库根目录，库先 `make db-up`）：

    python backend/scripts/measure_dashboard_summary.py --requests 20
    python backend/scripts/measure_dashboard_summary.py --market-json ~/base.json

`--market-json` 把响应的 `market` 段按固定键序写成 JSON，改前落一份、改后落一份，
`diff` 为空即「涨跌家数与共振强度逐项一致」。只写与取数路径有关的项：`as_of` 与
`session` 随请求时刻变化，把它们写进去只会让 diff 常年不空。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, event

BACKEND_DIR = Path(__file__).resolve().parents[1]
# 脚本通常以仓库根为 cwd 运行，`app` 包在 backend/ 下，需要显式加入搜索路径。
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402  路径注入后再导入

from app.main import create_app  # noqa: E402

DASHBOARD_PATH = "/api/dashboard/summary"


@contextmanager
def _count_statements() -> Iterator[list[str]]:
    """在引擎类上挂计数器：返回列表里每一条都是这次统计窗口内发出的一条 SQL。"""

    issued: list[str] = []

    def _record(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        issued.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield issued
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


def _comparable(market: dict) -> dict:
    """只留与取数路径有关的项：`as_of` 与 `session` 随请求时刻变化，不参与比对。"""

    return {
        item["inst_type"]: {
            "bar": item["bar"],
            "breadth": item["breadth"],
            "resonance": item["resonance"],
        }
        for item in market["data"]["items"]
    }


def _percentile(values: list[float], ratio: float) -> float:
    """最近秩法分位数：样本少时不用插值，取真实观测到的那个值。"""

    ordered = sorted(values)
    rank = max(1, math.ceil(ratio * len(ordered)))
    return ordered[rank - 1]


def _measure(client: TestClient, requests: int, warmup: int) -> tuple[list[int], list[float]]:
    """预热后连续请求 `requests` 次，返回每次的 SQL 条数与耗时（秒）。"""

    for _ in range(warmup):
        client.get(DASHBOARD_PATH)

    counts: list[int] = []
    durations: list[float] = []
    for _ in range(requests):
        with _count_statements() as issued:
            started = time.perf_counter()
            response = client.get(DASHBOARD_PATH)
            durations.append(time.perf_counter() - started)
        response.raise_for_status()
        counts.append(len(issued))
    return counts, durations


def _report(counts: list[int], durations: list[float]) -> None:
    ms = [value * 1000 for value in durations]
    unique_counts = sorted(set(counts))
    count_text = str(unique_counts[0]) if len(unique_counts) == 1 else str(unique_counts)
    print(f"请求次数: {len(ms)}")
    print(f"SQL 条数（每次请求）: {count_text}")
    print(f"延迟 ms — p50: {_percentile(ms, 0.50):.1f}")
    print(f"延迟 ms — p95: {_percentile(ms, 0.95):.1f}")
    print(f"延迟 ms — p99: {_percentile(ms, 0.99):.1f}")
    print(f"延迟 ms — 均值: {statistics.fmean(ms):.1f}")
    print(f"延迟 ms — 最小/最大: {min(ms):.1f} / {max(ms):.1f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20, help="计入统计的请求次数")
    parser.add_argument("--warmup", type=int, default=3, help="预热请求次数，不计入统计")
    parser.add_argument("--market-json", type=Path, help="把响应的 market 段写到该文件")
    args = parser.parse_args()
    if args.requests < 1:
        parser.error("--requests 至少为 1")
    if args.warmup < 0:
        parser.error("--warmup 不能为负")

    # 每次请求都打一条 INFO 日志，量指标时只会埋掉结果。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = TestClient(create_app())
    counts, durations = _measure(client, args.requests, args.warmup)
    _report(counts, durations)

    if args.market_json is not None:
        market = client.get(DASHBOARD_PATH).json()["market"]
        text = json.dumps(_comparable(market), indent=2, ensure_ascii=False, sort_keys=True)
        args.market_json.write_text(text + "\n", encoding="utf-8")
        print(f"market 段已写入 {args.market_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
