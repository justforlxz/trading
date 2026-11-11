"""把 OKX 的逐仓档位表录制成测试夹具。

只读公共接口 `/api/v5/public/position-tiers`，**不带任何凭证**：按 `instFamily`
拉取逐仓（`tdMode=isolated`）的档位，逐行裁剪到保证金模型认识的字段，写进
`tests/fixtures/okx/` 的冻结快照。档位是静态规则（不随行情变化），因此快照不带
时间序列，只记录录制时刻。

产物是测试夹具，不是实时规则源；生产代码按 `instFamily` 实时查询上游。

用法（仓库根目录或 backend/ 下均可）：

    python backend/scripts/record_okx_position_tiers.py
    python backend/scripts/record_okx_position_tiers.py --inst-family AAPL-USDT
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures" / "okx"

OKX_BASE_URL = "https://www.okx.com"
POSITION_TIERS_PATH = "/api/v5/public/position-tiers"
DEFAULT_INST_FAMILY = "AAPL-USDT"
#: 保证金模式固定逐仓（D1 实施约束），因此只录制这一个模式。
TD_MODE = "isolated"
TIMEOUT_SECONDS = 30.0
USER_AGENT = "trading-backend-test-fixture-recorder/1.0"

#: 保证金模型用到的字段加上游原样保留的标识字段。
FIELDS: tuple[str, ...] = (
    "instFamily",
    "uly",
    "instId",
    "tier",
    "minSz",
    "maxSz",
    "imr",
    "mmr",
    "maxLever",
)


def position_tiers_url(
    inst_family: str, *, base_url: str = OKX_BASE_URL, td_mode: str = TD_MODE
) -> str:
    query = urllib.parse.urlencode(
        {"instType": "SWAP", "tdMode": td_mode, "instFamily": inst_family}
    )
    return f"{base_url}{POSITION_TIERS_PATH}?{query}"


def fetch_position_tiers(
    inst_family: str, *, base_url: str = OKX_BASE_URL, timeout: float = TIMEOUT_SECONDS
) -> list[dict[str, str]]:
    """拉取一个 `instFamily` 的逐仓档位；上游非零 code 或空档位表都视为失败。"""

    url = position_tiers_url(inst_family, base_url=base_url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # 只读公共接口，不带凭证；urlopen 的 scheme 由本模块拼装，不来自外部输入。
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: dict[str, Any] = json.load(response)
    if payload.get("code") != "0":
        raise SystemExit(f"上游返回错误:{url} code={payload.get('code')} msg={payload.get('msg')}")
    rows = payload.get("data") or []
    if not rows:
        raise SystemExit(f"上游没有返回任何档位:{url}")
    return rows


def project_row(row: dict[str, Any]) -> dict[str, str]:
    """只保留 `FIELDS` 里的字段，值原样转成字符串（上游给的就是字符串）。"""

    return {field: str(row.get(field, "")) for field in FIELDS}


def default_output_path(inst_family: str, captured_at: datetime) -> Path:
    return FIXTURES_DIR / f"position_tiers_{inst_family}_{captured_at:%Y-%m-%d}.json"


def build_document(
    rows: list[dict[str, str]],
    *,
    inst_family: str,
    captured_at: datetime,
    base_url: str = OKX_BASE_URL,
) -> dict[str, Any]:
    """装配快照文档；`tier` 号必须从 1 连续到行数，否则说明上游少给了档位。"""

    tiers = sorted(int(row["tier"]) for row in rows)
    if tiers != list(range(1, len(rows) + 1)):
        raise SystemExit(f"档位号不连续: 期望 1..{len(rows)}, 实际 {tiers[:5]}…")
    return {
        "meta": {
            "kind": "test_fixture_frozen_snapshot",
            "purpose": (
                "测试夹具: OKX 永续逐仓档位表的冻结快照。仅供自动化测试使用, "
                "不是实时规则源, 不得作为生产数据源。"
            ),
            "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": position_tiers_url(inst_family, base_url=base_url),
            "filter": f"instType=SWAP, tdMode={TD_MODE}, instFamily={inst_family}",
            "counts": {"tiers": len(rows)},
            "fields": list(FIELDS),
            "notes": [
                "maxSz / minSz 是上游的持仓规模单位: USDT 本位永续为张数。",
                "mmr 是维持保证金率, imr 是初始保证金率, maxLever 是该档可用杠杆上限。",
                "字段值全部原样来自 OKX 响应 (字符串保留原格式, 缺失字段记为空串)。",
            ],
        },
        "position_tiers": rows,
    }


def render_document(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inst-family", default=DEFAULT_INST_FAMILY)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--base-url", default=OKX_BASE_URL)
    args = parser.parse_args(argv)

    captured_at = datetime.now(UTC)
    rows = [
        project_row(row) for row in fetch_position_tiers(args.inst_family, base_url=args.base_url)
    ]
    document = build_document(
        rows,
        inst_family=args.inst_family,
        captured_at=captured_at,
        base_url=args.base_url,
    )
    output = args.out or default_output_path(args.inst_family, captured_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_document(document), encoding="utf-8")
    print(f"已写入 {output} : {len(rows)} 档")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
