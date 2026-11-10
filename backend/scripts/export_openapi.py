"""把 FastAPI 应用的真实路由导出为契约文件 `contracts/openapi.json`。

契约是前端类型与 MSW fixture 的唯一来源，因此导出必须是**确定性**的：
同一份代码重复导出得到逐字节相同的文件，`git diff --exit-code` 才有意义。

用法（仓库根目录）：`python backend/scripts/export_openapi.py`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# 脚本通常以仓库根为 cwd 运行，`app` 包在 backend/ 下，需要显式加入搜索路径。
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import create_app  # noqa: E402  路径注入后再导入

CONTRACT_PATH = BACKEND_DIR / "contracts" / "openapi.json"


def render_contract() -> str:
    """确定性序列化：键排序 + 固定缩进 + 结尾换行。"""

    document = create_app().openapi()
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(render_contract(), encoding="utf-8")
    print(f"wrote {CONTRACT_PATH.relative_to(BACKEND_DIR.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
