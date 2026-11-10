"""架构门禁：`app/core/` 必须是叶子。

core 是跨模块公共层，每个模块都依赖它。它一旦反过来依赖任何业务模块，就会出现
循环依赖：改业务模块会牵动 core，改 core 又会牵动全仓，并行开发立刻失效。

主门禁（`test_import_graph.py`）通过 `INFRA` 允许任意模块导入 core，但那条规则同时
也会放行「core 反过来导入 config」。真正的叶子约束在本文件：core 只能导入自己的
子模块。

负向用例用 tmp 目录里构造的 `app/core/` 树驱动同一个扫描器——保证门禁本身不会退化
成空断言，又不必污染真实源码树。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
CORE_ROOT = APP_ROOT / "core"

#: core 允许导入的 app 子包只有它自己。
ALLOWED_PACKAGE = "core"


@dataclass(frozen=True)
class Violation:
    """一处越界导入。"""

    path: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


def _package_of(source: Path, root: Path) -> str:
    """`app/core/ports/trade.py` 所在的包名：`app.core.ports`。"""

    parts = source.relative_to(root).parts
    package_parts = ("app", "core", *parts[:-1])
    return ".".join(package_parts)


def _resolve(node: ast.ImportFrom, package: str) -> str:
    """把 `from X import Y` 解析成完整的模块名，相对导入按所在包展开。"""

    if not node.level:
        return node.module or ""
    parts = package.split(".")
    base = parts[: len(parts) - node.level + 1]
    if node.module:
        base = [*base, *node.module.split(".")]
    return ".".join(base)


def _imported_modules(tree: ast.AST, package: str) -> list[tuple[int, str]]:
    """收集 (行号, 完整模块名)。"""

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, _resolve(node, package)))
    return found


def scan_core(root: Path) -> list[Violation]:
    """扫描 core 源码树，返回所有指向 app 其它模块的导入。"""

    problems: list[Violation] = []
    for source in sorted(root.rglob("*.py")):
        package = _package_of(source, root)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for line, module in _imported_modules(tree, package):
            parts = module.split(".")
            # 标准库、第三方库不属于本门禁的管辖范围。
            if not parts or parts[0] != "app":
                continue
            # `import app` 只是拿到包对象，没有建立模块级依赖。
            if len(parts) == 1:
                continue
            if parts[1] == ALLOWED_PACKAGE:
                continue
            problems.append(
                Violation(
                    path=str(source.relative_to(root.parent.parent)),
                    line=line,
                    reason=f"core 是叶子: 不得依赖 app.{parts[1]}",
                )
            )
    return problems


def test_core_tree_imports_nothing_but_itself() -> None:
    """真实的 core 源码树零越界。"""

    assert scan_core(CORE_ROOT) == []


@pytest.mark.parametrize(
    "source",
    [
        "import app.exchange\n",
        "from app.exchange import OkxClient\n",
        "from app.market.candles import load\n",
        "from app.config import get_settings\n",
    ],
)
def test_leaf_gate_flags_absolute_business_import(tmp_path: Path, source: str) -> None:
    """负向：任何 app 下的非 core 模块都必须被拦下。"""

    core_root = tmp_path / "app" / "core"
    core_root.mkdir(parents=True)
    (core_root / "probe.py").write_text(source, encoding="utf-8")

    problems = scan_core(core_root)

    assert len(problems) == 1
    assert problems[0].line == 1
    assert "不得依赖" in problems[0].reason


def test_leaf_gate_resolves_relative_import_escape(tmp_path: Path) -> None:
    """负向：相对导入不能成为绕过门禁的暗道。

    `app/core/ports/adapt.py` 里的 `from ...exchange import X` 解析后是
    `app.exchange`，已经跑到 core 之外。
    """

    ports = tmp_path / "app" / "core" / "ports"
    ports.mkdir(parents=True)
    (ports / "adapt.py").write_text("from ...exchange import OkxClient\n", encoding="utf-8")

    problems = scan_core(tmp_path / "app" / "core")

    assert len(problems) == 1
    assert problems[0].reason.endswith("app.exchange")


def test_leaf_gate_allows_internal_relative_import(tmp_path: Path) -> None:
    """core 内部互相导入是正常的（门禁只拦跨模块）。"""

    ports = tmp_path / "app" / "core" / "ports"
    ports.mkdir(parents=True)
    (ports / "adapt.py").write_text(
        "from ..errors import ValidationError\n",
        encoding="utf-8",
    )

    assert scan_core(tmp_path / "app" / "core") == []
