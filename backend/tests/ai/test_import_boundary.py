"""P4-01: `app.ai` 的 import 白名单门禁。

`app.ai` 只能 import `app.ai.*` / `app.ports.ai_reads` / `app.config` / `app.db.session`
与第三方依赖; 任何业务域模块 (market/research/opportunity/strategy/backtest/risk/
execution/ops) 都不允许出现。域数据一律走 `app.ports.ai_reads` 端口, 实现放在
`app/adapters/domain`。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = BACKEND_ROOT / "app" / "ai"
DOMAIN_ADAPTER = BACKEND_ROOT / "app" / "adapters" / "domain" / "reads.py"

ALLOWED_APP_MODULES = (
    "app.ai",
    "app.ports.ai_reads",
    "app.config",
    "app.db.session",
)
# 非标准库的第三方依赖: 只有 provider HTTP 客户端与 SQLAlchemy (审计写入)。
ALLOWED_THIRD_PARTY = frozenset({"httpx", "sqlalchemy"})


def _modules_of(tree: ast.Module) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入: 顶层模块由所在包决定, 不参与判定。
                continue
            if node.module:
                modules.append(node.module)
    return modules


def test_ai_imports_stay_within_whitelist() -> None:
    files = sorted(AI_ROOT.rglob("*.py"))
    assert files, "app.ai 下没有找到任何模块"

    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _modules_of(tree):
            top = module.split(".")[0]
            if top == "app":
                allowed = any(
                    module == name or module.startswith(f"{name}.") for name in ALLOWED_APP_MODULES
                )
                if not allowed:
                    violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
            elif top not in sys.stdlib_module_names and top not in ALLOWED_THIRD_PARTY:
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")

    assert not violations, "app.ai 出现白名单之外的 import: " + "; ".join(violations)


def test_domain_reads_adapter_exists() -> None:
    assert DOMAIN_ADAPTER.is_file(), "域只读适配器缺失: app/adapters/domain/reads.py"
