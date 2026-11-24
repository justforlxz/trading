"""量 `/api/dashboard/summary` 一次请求的 SQL 条数与延迟。

改前改后用同一份脚本、同一份库数据量，数字才有可比性。计数器挂在 SQLAlchemy 的
`before_cursor_execute` 上，只统计请求处理期间真正发到库里的语句；预热请求不计入。

语句还要按首页模块归属。`app.dashboard.service` 里每个模块都调用本模块命名空间里的
一个入口（`market_overview` / `exposure_report` / `merge_positions` / …），脚本在统计
窗口内把这些入口换成「先登记当前模块、再原样调用」的包装函数，于是每条语句落到发起
它的那个模块名下；没有归到任何模块的语句（请求会话、装配、设置读取）记在「其它」。

用法（仓库根目录，库先 `make db-up`）：

    python backend/scripts/measure_dashboard_summary.py --requests 20
    python backend/scripts/measure_dashboard_summary.py --market-json ~/base.json
    python backend/scripts/measure_dashboard_summary.py --sections-json ~/base.json

`--market-json` 把响应的 `market` 段按固定键序写成 JSON，`--sections-json` 写 `risk` /
`positions` / `watchlist` 三段与 `GET /api/risk/exposure` 的完整输出。改前落一份、改后
落一份，`diff` 为空即「逐项一致」。两处都丢掉 `as_of` 这类随请求时刻变化的字段：
写进去只会让 diff 常年不空。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event

BACKEND_DIR = Path(__file__).resolve().parents[1]
# 脚本通常以仓库根为 cwd 运行，`app` 包在 backend/ 下，需要显式加入搜索路径。
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402  路径注入后再导入

from app.main import create_app  # noqa: E402

DASHBOARD_PATH = "/api/dashboard/summary"
EXPOSURE_PATH = "/api/risk/exposure"
OTHER = "其它"

#: 首页每个模块在 `app.dashboard.service` 里的装配函数名。统计的是「这个模块装载期间
#: 发出了多少条 SQL」，因此用模块自己的入口，而不是它调用的取数函数——同一次读取可能
#: 被两个模块共用，算在触发它的模块名下才符合「这一段做多少活」。
SECTION_ENTRIES: dict[str, tuple[str, ...]] = {
    "market": ("_market",),
    "account": ("_account",),
    "risk": ("_risk",),
    "positions": ("_positions",),
    "watchlist": ("_watchlist",),
    "alerts": ("_alerts",),
    "strategies": ("_strategies",),
    "activity": ("_activity",),
}

SECTION_NAMES: tuple[str, ...] = (*SECTION_ENTRIES, OTHER)

#: `--sections-json` 比对的三段；敞口的完整输出另从 `/api/risk/exposure` 取。
COMPARED_SECTIONS: tuple[str, ...] = ("risk", "positions", "watchlist")

#: 本单改成批量取数的三段；「三段合计」按每请求的耗时相加后再取分位数。
BATCHED_SECTIONS: tuple[str, ...] = ("risk", "watchlist", "positions")


def _mark(
    section: str,
    function: Callable[..., Any],
    current: dict[str, str | None],
    durations: dict[str, float],
) -> Callable[..., Any]:
    """包一层：调用期间把「当前模块」登记成 `section`，并累加它的耗时（毫秒）。"""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        previous = current["section"]
        current["section"] = section
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            current["section"] = previous
            durations[section] = durations.get(section, 0.0) + (time.perf_counter() - started)

    return wrapper


@contextmanager
def _attribute_statements(
    current: dict[str, str | None],
    durations: dict[str, float],
) -> Iterator[None]:
    """统计窗口内把模块入口换成登记器；退出时原样换回。"""

    module = sys.modules["app.dashboard.service"]
    original: dict[str, Callable[..., Any]] = {}
    try:
        for section, entries in SECTION_ENTRIES.items():
            for entry in entries:
                function = getattr(module, entry, None)
                if function is None or entry in original:
                    continue
                original[entry] = function
                setattr(module, entry, _mark(section, function, current, durations))
        yield
    finally:
        for entry, function in original.items():
            setattr(module, entry, function)


@contextmanager
def _count_statements(current: dict[str, str | None]) -> Iterator[dict[str, int]]:
    """在引擎类上挂计数器：按「当前模块」累加这次统计窗口内发出的 SQL 条数。"""

    counts: dict[str, int] = {}

    def _record(
        _conn: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        key = current["section"] or OTHER
        counts[key] = counts.get(key, 0) + 1

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield counts
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


def _strip_volatile(value: Any) -> Any:
    """递归丢掉 `as_of`：它随请求时刻变化，参与比对只会让 diff 常年不空。"""

    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in value.items() if key != "as_of"}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


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


def _measure(
    client: TestClient, requests: int, warmup: int
) -> tuple[list[dict[str, int]], list[float], list[dict[str, float]]]:
    """预热后连续请求 `requests` 次。

    返回每次请求的「按模块 SQL 条数」、整次耗时（毫秒）与「按模块耗时」（毫秒）。
    按模块耗时是每请求各自一份，才能对每一段分别取分位数；把各次请求相加再除只
    得到均值，均值的尾部没有意义。
    """

    for _ in range(warmup):
        client.get(DASHBOARD_PATH)

    current: dict[str, str | None] = {"section": None}
    durations: dict[str, float] = {}
    per_request_counts: list[dict[str, int]] = []
    per_request_ms: list[dict[str, float]] = []
    totals: list[float] = []
    with _attribute_statements(current, durations):
        for _ in range(requests):
            durations.clear()
            with _count_statements(current) as counts:
                started = time.perf_counter()
                response = client.get(DASHBOARD_PATH)
                totals.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            per_request_counts.append(counts)
            per_request_ms.append({name: value * 1000 for name, value in durations.items()})
    return per_request_counts, totals, per_request_ms


def _count_text(values: list[int]) -> str:
    unique = sorted(set(values))
    return str(unique[0]) if len(unique) == 1 else str(unique)


def _report(
    per_request_counts: list[dict[str, int]],
    totals: list[float],
    per_request_ms: list[dict[str, float]],
) -> None:
    statement_totals = [sum(counts.values()) for counts in per_request_counts]
    print(f"请求次数: {len(totals)}")
    print(f"SQL 条数（每次请求）: {_count_text(statement_totals)}")
    print(f"整次请求 ms — p50: {_percentile(totals, 0.50):.1f}")
    print(f"整次请求 ms — p95: {_percentile(totals, 0.95):.1f}")
    print(f"整次请求 ms — p99: {_percentile(totals, 0.99):.1f}")
    print(f"整次请求 ms — 均值: {statistics.fmean(totals):.1f}")
    print(f"整次请求 ms — 最小/最大: {min(totals):.1f} / {max(totals):.1f}")
    print("按模块（SQL 条数 / 该段 p50 ms / 该段 p95 ms）:")
    for name in SECTION_NAMES:
        values = [counts.get(name, 0) for counts in per_request_counts]
        section_ms = [request.get(name, 0.0) for request in per_request_ms]
        print(
            f"  {name:<10} {_count_text(values):<8} "
            f"{_percentile(section_ms, 0.50):8.1f} {_percentile(section_ms, 0.95):8.1f}"
        )
    combined = [
        sum(request.get(name, 0.0) for name in BATCHED_SECTIONS) for request in per_request_ms
    ]
    print(
        f"  {'三段合计':<8} {'-':<8} "
        f"{_percentile(combined, 0.50):8.1f} {_percentile(combined, 0.95):8.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20, help="计入统计的请求次数")
    parser.add_argument("--warmup", type=int, default=3, help="预热请求次数，不计入统计")
    parser.add_argument("--market-json", type=Path, help="把响应的 market 段写到该文件")
    parser.add_argument(
        "--sections-json",
        type=Path,
        help="把 risk / positions / watchlist 三段与完整敞口写到该文件",
    )
    args = parser.parse_args()
    if args.requests < 1:
        parser.error("--requests 至少为 1")
    if args.warmup < 0:
        parser.error("--warmup 不能为负")

    # 每次请求都打一条 INFO 日志，量指标时只会埋掉结果。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = TestClient(create_app())
    per_request_counts, totals, per_request_ms = _measure(client, args.requests, args.warmup)
    _report(per_request_counts, totals, per_request_ms)

    if args.market_json is not None:
        market = client.get(DASHBOARD_PATH).json()["market"]
        text = json.dumps(_comparable(market), indent=2, ensure_ascii=False, sort_keys=True)
        args.market_json.write_text(text + "\n", encoding="utf-8")
        print(f"market 段已写入 {args.market_json}")

    if args.sections_json is not None:
        summary = client.get(DASHBOARD_PATH).json()
        sections = {name: _strip_volatile(summary[name]) for name in COMPARED_SECTIONS}
        sections["exposure"] = _strip_volatile(client.get(EXPOSURE_PATH).json())
        text = json.dumps(sections, indent=2, ensure_ascii=False, sort_keys=True)
        args.sections_json.write_text(text + "\n", encoding="utf-8")
        print(f"risk / positions / watchlist 与敞口已写入 {args.sections_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
