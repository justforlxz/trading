"""把 OKX 的公共标的清单录制成测试夹具。

只读公共接口 `/api/v5/public/instruments`，**不带任何凭证**：按 `instType` 分别
拉取，逐行裁剪到下游适配层认识的字段，写进 `tests/fixtures/okx/` 的冻结快照。

与既有快照 `instruments_2026-11-10.json` 的区别是这里**不筛选**：上游返回的全部
标的都记录，因此 `instCategory` 覆盖 `3`（代币化股票）、`1`（加密）、`4`（代币化
商品）与空串（尚未开盘的行）。

产物是测试夹具，不是实时行情，不得作为生产数据源。

用法（仓库根目录或 backend/ 下均可）：

    python backend/scripts/record_okx_instruments.py
    python backend/scripts/record_okx_instruments.py --out ../tests/fixtures/okx/x.json
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures" / "okx"

OKX_BASE_URL = "https://www.okx.com"
INSTRUMENTS_PATH = "/api/v5/public/instruments"
INST_TYPES: tuple[str, ...] = ("SPOT", "SWAP")
TIMEOUT_SECONDS = 30.0
# 上游对缺少 User-Agent 的请求直接返回 403；这里显式标明是夹具录制工具。
USER_AGENT = "trading-backend-test-fixture-recorder/1.0"

# 与既有快照保持同一份字段清单：适配层用到的字段加上游原样保留的标识字段。
FIELDS: tuple[str, ...] = (
    "instType",
    "instId",
    "instCategory",
    "state",
    "baseCcy",
    "quoteCcy",
    "ctValCcy",
    "uly",
    "instFamily",
    "tickSz",
    "lotSz",
    "minSz",
    "listTime",
    "ctVal",
    "ctMult",
    "ctType",
    "lever",
    "settleCcy",
    "openType",
    "ruleType",
    "category",
    "alias",
)


def instruments_url(inst_type: str, *, base_url: str = OKX_BASE_URL) -> str:
    query = urllib.parse.urlencode({"instType": inst_type})
    return f"{base_url}{INSTRUMENTS_PATH}?{query}"


def fetch_instruments(
    inst_type: str, *, base_url: str = OKX_BASE_URL, timeout: float = TIMEOUT_SECONDS
) -> list[dict[str, str]]:
    """拉取一类标的的原始行；上游返回非零 code 视为失败，不写半份夹具。"""

    url = instruments_url(inst_type, base_url=base_url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # 只读公共接口，不带凭证；urlopen 的 scheme 由本模块拼装，不来自外部输入。
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: dict[str, Any] = json.load(response)
    if payload.get("code") != "0":
        raise SystemExit(f"上游返回错误:{url} code={payload.get('code')} msg={payload.get('msg')}")
    rows = payload.get("data") or []
    if not rows:
        raise SystemExit(f"上游没有返回任何标的:{url}")
    return rows


def project_row(row: dict[str, Any]) -> dict[str, str]:
    """只保留 `FIELDS` 里的字段，值原样转成字符串（上游给的就是字符串）。"""

    return {field: str(row.get(field, "")) for field in FIELDS}


def default_output_path(captured_at: datetime) -> Path:
    return FIXTURES_DIR / f"instruments_all_{captured_at:%Y-%m-%d}.json"


def build_document(
    rows: list[dict[str, str]], *, captured_at: datetime, base_url: str = OKX_BASE_URL
) -> dict[str, Any]:
    """装配快照文档：`counts` 按 instType 求和等于行数，`category_counts` 按 instCategory。"""

    by_type = Counter(row["instType"] for row in rows)
    by_category = Counter(row["instCategory"] for row in rows)
    counts = {inst_type: by_type[inst_type] for inst_type in sorted(by_type)}
    if sum(counts.values()) != len(rows):
        raise SystemExit(f"按类别的计数之和与行数不符:{sum(counts.values())} != {len(rows)}")

    sources = " 与 ".join(
        f"{base_url}{INSTRUMENTS_PATH}?instType={inst_type}" for inst_type in INST_TYPES
    )
    return {
        "meta": {
            "kind": "test_fixture_frozen_snapshot",
            "purpose": (
                "测试夹具: OKX 全类别标的清单的冻结快照。仅供自动化测试使用, "
                "不是实时行情, 不得作为生产数据源或对外声称真实行情。"
            ),
            "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": sources,
            "filter": "不筛选: 按 instType 原样记录上游公共接口返回的全部标的",
            "counts": counts,
            "category_counts": {
                category: by_category[category] for category in sorted(by_category)
            },
            "fields": list(FIELDS),
            "notes": [
                "instCategory 是上游的资产类别: 3 代币化股票/ETF, 1 加密资产, "
                "4 代币化商品; 空串表示上游未下发 (尚未开盘的 preopen 行)。",
                "SPOT 与 SWAP 各自包含全部报价币种, 不只看 USDT 计价; "
                "preopen 行的 tickSz / lotSz / minSz 为空串, 与上游一致。",
                "字段值全部原样来自 OKX 响应 (字符串保留原格式, 缺失字段记为空串)。",
            ],
        },
        "instruments": rows,
    }


def render_document(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="录制 OKX 全类别标的清单测试夹具")
    parser.add_argument("--out", type=Path, help="输出路径 (默认按抓取日期写进 tests/fixtures/okx)")
    parser.add_argument(
        "--base-url", default=OKX_BASE_URL, help="上游地址, 默认 https://www.okx.com"
    )
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS, help="单次请求超时秒数")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    captured_at = datetime.now(UTC)
    rows = [
        project_row(row)
        for inst_type in INST_TYPES
        for row in fetch_instruments(inst_type, base_url=args.base_url, timeout=args.timeout)
    ]
    rows.sort(key=lambda row: (row["instType"], row["instId"]))
    document = build_document(rows, captured_at=captured_at, base_url=args.base_url)

    output_path = args.out or default_output_path(captured_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_document(document), encoding="utf-8")
    print(f"wrote {output_path} counts={document['meta']['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
