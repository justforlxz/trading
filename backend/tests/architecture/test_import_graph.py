"""架构门禁：模块依赖矩阵 + 导入形态 + 门面（规则唯一真源 `ALLOWED_DEPS`）。

三条强制全部是会红的测试，不是文档：

1. 门面 —— 每个 `app/<模块>/__init__.py` 显式声明 `__all__`，门面里的名字真的
   解析到模块对象；跨包导入必须落在对方门面发布的名字里；门面不得有死导出。
2. 导入形态 —— 跨模块只允许 `from app.<模块> import ...` / `import app.<模块>`；
   子模块直连（`from app.<模块>.<子模块> import ...`）、`sys.path` 注入、
   相对导入越界、导入测试包，一律判违规。
3. 矩阵 —— 逐边比对 `ALLOWED_DEPS`，未登记的依赖边即失败。

扫描器只做 AST 静态解析，不 import 被扫描的源码；负向用例用构造的源码驱动，
因此「扫描器坏了」和「代码违规了」不会混成同一个红。
"""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
TESTS_ROOT = BACKEND_ROOT / "tests"

# 业务包清单：与 `app/` 下的目录一一对应；新增模块必须先在此登记。
PACKAGES: tuple[str, ...] = (
    "api",
    "backtest",
    "core",
    "db",
    "exchange",
    "execution",
    "indicators",
    "instrument",
    "jobs",
    "journal",
    "market",
    "risk",
    "shared",
    "strategy",
    "watchlist",
)

# 基础设施叶子：进程级配置单例，不属于业务包。任何模块都可依赖它，它不依赖任何
# 业务包；单独列出而不是写进每一行，避免矩阵被同一项噪音淹没。
#
# `core` 同样在此：它是跨模块公共层（错误/值对象/端口），每个模块都要用，但它自己
# 只依赖外部库。严格的「core 谁也不依赖」由 `test_core_is_leaf.py` 单独把关，这里
# 登记是为了不用在每行矩阵里重复写一遍。
INFRA: frozenset[str] = frozenset({"config", "core"})

# 唯一真源：模块 → 允许依赖的模块集合（规划 MKACG-707 定稿，逐行即契约）。
# `jobs` / `api` 是装配层（"全部"），`main` 是装配根，`config` / `core` 是叶子。
ALLOWED_DEPS: dict[str, frozenset[str]] = {
    "core": frozenset(),
    "shared": frozenset(),
    "db": frozenset({"shared"}),
    "exchange": frozenset({"shared", "instrument"}),
    "instrument": frozenset({"shared", "db"}),
    "market": frozenset({"shared", "db", "exchange", "instrument"}),
    "watchlist": frozenset({"shared", "db", "instrument", "market"}),
    "indicators": frozenset({"shared"}),
    "strategy": frozenset({"shared", "db", "instrument", "market", "indicators"}),
    "backtest": frozenset({"shared", "db", "instrument", "market", "strategy"}),
    "risk": frozenset({"shared", "db", "instrument", "market", "strategy"}),
    "execution": frozenset(
        {"shared", "db", "instrument", "market", "strategy", "risk", "exchange"}
    ),
    "journal": frozenset({"shared", "db", "backtest", "execution", "strategy"}),
    "jobs": frozenset(PACKAGES) - {"jobs"},
    "api": frozenset(PACKAGES) - {"api"},
    "main": frozenset(PACKAGES),
    "config": frozenset(),
}


def allowed_for(module: str) -> frozenset[str]:
    """模块的允许依赖 = 矩阵行 + 基础设施叶子。

    叶子集合里同时包含本模块时（`core` 就是这种情况）要减掉自己，否则矩阵行
    `frozenset()` 与「任何模块都可依赖 core」会互相抵消，让 core 可以依赖自己。
    """

    return (ALLOWED_DEPS.get(module, frozenset()) | INFRA) - {module}


@dataclass(frozen=True)
class Violation:
    """一条导入违规：定位到文件/行，并给出人可读的原因。"""

    path: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


def _resolve_relative(package: str, level: int, module: str | None) -> str | None:
    """把相对导入解析为绝对模块名；越出 `app` 边界返回 `None`。"""

    parts = package.split(".")
    if level > len(parts):
        return None
    base = parts[: len(parts) - level + 1]
    if not base:
        return None
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _is_sys_path(expr: ast.AST) -> bool:
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == "path"
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "sys"
    )


def _import_violations(tree: ast.AST, *, module: str, package: str, path: str) -> list[Violation]:
    found: list[Violation] = []
    allowed = allowed_for(module)

    def flag(node: ast.AST, reason: str) -> None:
        found.append(Violation(path, getattr(node, "lineno", 0), reason))

    def check(node: ast.AST, target: str, depth: int) -> None:
        """`target` 是 `app.<target>...` 的第一段；`depth` 是 app 之后剩余的段数。"""

        if target == module:
            return  # 同包内部导入：门面内务，不构成跨模块依赖
        if target == "tests":
            flag(node, "生产代码不得导入测试包 `tests`")
            return
        if target not in ALLOWED_DEPS:
            flag(node, f"未知模块 `app.{target}`:不在模块矩阵内")
            return
        if depth > 1:
            flag(node, f"跨模块导入子模块 `app.{target}.*`:必须经门面 `app.{target}`")
            return
        if target not in allowed:
            flag(node, f"`{module}` 不允许依赖 `{target}`(见 ALLOWED_DEPS)")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "tests":
                    flag(node, "生产代码不得导入测试包 `tests`")
                elif parts[0] == "app" and len(parts) > 1:
                    check(node, parts[1], len(parts) - 1)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                resolved = _resolve_relative(package, node.level, node.module)
                if resolved is None:
                    flag(node, f"相对导入越界(level={node.level}, package={package})")
                    continue
                parts = resolved.split(".")
            elif node.module:
                parts = node.module.split(".")
            else:
                continue
            if parts[0] == "tests":
                flag(node, "生产代码不得导入测试包 `tests`")
                continue
            if parts[0] != "app":
                continue  # 标准库/第三方
            if len(parts) == 1:
                # `from app import x`：x 若是业务包名，等价于依赖该包
                for alias in node.names:
                    if alias.name in ALLOWED_DEPS:
                        check(node, alias.name, 1)
                continue
            check(node, parts[1], len(parts) - 1)
    return found


def _path_injection_violations(tree: ast.AST, *, path: str) -> list[Violation]:
    """`sys.path` 改写等于绕过包结构，直接判违规。"""

    found: list[Violation] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "insert", "extend"}
            and _is_sys_path(node.func.value)
        ):
            found.append(Violation(path, node.lineno, "禁止改写 `sys.path` 注入模块路径"))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if _is_sys_path(target) or (
                    isinstance(target, ast.Subscript) and _is_sys_path(target.value)
                ):
                    found.append(Violation(path, node.lineno, "禁止改写 `sys.path` 注入模块路径"))
    return found


def scan_source(
    source: str, *, module: str, package: str, path: str = "<memory>"
) -> list[Violation]:
    """扫描一段源码。纯函数：不落盘、不 import，负向用例直接喂构造字符串。"""

    tree = ast.parse(source, filename=path)
    return _import_violations(tree, module=module, package=package, path=path) + (
        _path_injection_violations(tree, path=path)
    )


def scan_tree(root: Path = APP_ROOT) -> list[Violation]:
    """扫描整棵树：`module` / `package` 由相对路径推出。"""

    violations: list[Violation] = []
    for file in sorted(root.rglob("*.py")):
        rel = file.relative_to(root)
        if len(rel.parts) > 1:
            module = rel.parts[0]
            package = "app." + ".".join(rel.parts[:-1])
        else:
            module = file.stem
            package = "app"
        violations += scan_source(
            file.read_text(encoding="utf-8"), module=module, package=package, path=str(rel)
        )
    return violations


# ------------------------------------------------------------------ 正向：真实代码


def test_app_tree_has_no_import_violations() -> None:
    """`backend/app/**` 零违规；红时逐条打印文件/行/原因。"""

    violations = scan_tree()
    assert not violations, "\n".join(str(item) for item in violations)


def test_app_packages_match_matrix() -> None:
    """磁盘上的包集合必须与矩阵登记一致：多出/缺少模块都要显式改矩阵。"""

    on_disk = {
        path.name for path in APP_ROOT.iterdir() if path.is_dir() and path.name != "__pycache__"
    }
    assert on_disk == set(PACKAGES)


def test_matrix_is_self_consistent() -> None:
    assert set(ALLOWED_DEPS) == set(PACKAGES) | {"main", "config"}
    for module, deps in ALLOWED_DEPS.items():
        assert module not in deps, f"{module} 不能依赖自己"
        unknown = deps - set(ALLOWED_DEPS)
        assert not unknown, f"{module} 依赖了未登记的模块:{sorted(unknown)}"


# ------------------------------------------------------------- 门面：__all__ 三查


def _declared_all(init: Path) -> list[object]:
    """取 `__init__.py` 顶层 `__all__` 的字面量（支持 `=` 与 `: list[str] =`）。"""

    tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
    values: list[object] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            is_all = any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
        elif isinstance(node, ast.AnnAssign):
            is_all = isinstance(node.target, ast.Name) and node.target.id == "__all__"
        else:
            continue
        if is_all:
            values.append(ast.literal_eval(node.value))
    return values


def test_every_package_declares_explicit_all() -> None:
    problems: list[str] = []
    for name in PACKAGES:
        init = APP_ROOT / name / "__init__.py"
        if not init.is_file():
            problems.append(f"app/{name}/__init__.py 缺失")
            continue
        declared = _declared_all(init)
        if len(declared) != 1:
            problems.append(f"app/{name}/__init__.py 必须且只能显式声明一次 __all__")
            continue
        names = declared[0]
        if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
            problems.append(f"app/{name}/__init__.py 的 __all__ 必须是字符串列表")
            continue
        if len(set(names)) != len(names):
            problems.append(f"app/{name}/__init__.py 的 __all__ 有重复项")
        private = [item for item in names if item.startswith("_")]
        if private:
            problems.append(f"app/{name}/__init__.py 的 __all__ 不得发布私有名:{private}")
    assert not problems, "\n".join(problems)


def test_every_export_resolves_to_a_module_attribute() -> None:
    """门面不能是空承诺：`__all__` 里每个名字都要真的能取到。"""

    problems: list[str] = []
    for name in PACKAGES:
        module = importlib.import_module(f"app.{name}")
        for export in module.__all__:
            if not hasattr(module, export):
                problems.append(f"app.{name}.{export} 在 __all__ 里但模块上取不到")
    assert not problems, "\n".join(problems)


def _read_sources() -> dict[Path, str]:
    paths = [*APP_ROOT.rglob("*.py"), *TESTS_ROOT.rglob("*.py")]
    return {path: path.read_text(encoding="utf-8") for path in paths}


def test_no_export_is_dead() -> None:
    """门面不得发布无人使用的符号（规划 §6.1 的防腐化口径）。

    引用方可以是 `app/` 里的其它模块，也可以是 `tests/`；本模块自己不算引用方。
    """

    sources = _read_sources()
    problems: list[str] = []
    for name in PACKAGES:
        package_dir = APP_ROOT / name
        module = importlib.import_module(f"app.{name}")
        for export in module.__all__:
            pattern = re.compile(rf"(?<!\w){re.escape(export)}(?!\w)")
            users = [
                path.relative_to(BACKEND_ROOT).as_posix()
                for path, text in sources.items()
                if package_dir not in path.parents and pattern.search(text)
            ]
            if not users:
                problems.append(f"app.{name}.{export} 没有任何使用方(门面死导出)")
    assert not problems, "\n".join(problems)


def _cross_package_from_imports(root: Path) -> list[tuple[str, int, str, str]]:
    """收集 `from app.<包> import <名字>`：(文件, 行, 包, 名字)。"""

    rows: list[tuple[str, int, str, str]] = []
    for file in sorted(root.rglob("*.py")):
        rel = file.relative_to(root)
        module = rel.parts[0] if len(rel.parts) > 1 else file.stem
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            parts = node.module.split(".")
            if len(parts) != 2 or parts[0] != "app":
                continue
            package = parts[1]
            if package not in PACKAGES or package == module:
                continue
            for alias in node.names:
                rows.append((rel.as_posix(), node.lineno, package, alias.name))
    return rows


def test_cross_package_imports_use_published_names() -> None:
    """跨包只能拿门面发布过的名字：`from app.db import get_engine` 必须真的在
    `app.db.__all__` 里，否则等于绕过门面。"""

    problems: list[str] = []
    for path, line, package, name in _cross_package_from_imports(APP_ROOT):
        published = importlib.import_module(f"app.{package}").__all__
        if name not in published:
            problems.append(f"{path}:{line} 从 app.{package} 导入了未发布的 `{name}`")
    assert not problems, "\n".join(problems)


# ------------------------------------------------------- 负向：构造的违规源码


@pytest.mark.parametrize(
    ("reason", "module", "source"),
    [
        (
            "跨模块子模块直连",
            "market",
            "from app.db.engine import get_engine\n",
        ),
        (
            "矩阵禁止边 strategy→exchange",
            "strategy",
            "from app.exchange import OkxClient\n",
        ),
        (
            "反向依赖 market→strategy",
            "market",
            "import app.strategy\n",
        ),
        (
            "跨模块 import 子模块",
            "market",
            "import app.db.engine\n",
        ),
        (
            "导入测试包",
            "market",
            "from tests import conftest\n",
        ),
        (
            "相对导入越界",
            "market",
            "from ... import something\n",
        ),
        (
            "sys.path 注入",
            "market",
            "import sys\nsys.path.insert(0, 'app')\n",
        ),
    ],
)
def test_scanner_flags_constructed_violations(reason: str, module: str, source: str) -> None:
    violations = scan_source(source, module=module, package=f"app.{module}")
    assert violations, f"扫描器漏掉了违规形态:{reason}"
    assert all(item.reason for item in violations)


@pytest.mark.parametrize(
    ("reason", "source"),
    [
        ("门面导入", "from app.shared import normalize_bar\n"),
        ("允许边 market→db", "from app.db import init_db\n"),
        ("同包内部导入", "from app.market.candles import find_gaps\n"),
        ("同包相对导入", "from .candles import find_gaps\n"),
        ("导入 app 根", "import app\nfrom app import __version__\n"),
        ("依赖基础设施叶子", "from app.config import get_settings\n"),
        ("相对上跳到 app 根", "from .. import __version__\n"),
    ],
)
def test_scanner_accepts_allowed_forms(reason: str, source: str) -> None:
    violations = scan_source(source, module="market", package="app.market")
    assert not violations, f"{reason} 被误判:{[str(item) for item in violations]}"


def test_scan_tree_reports_violations_in_a_constructed_tree(tmp_path: Path) -> None:
    """树扫描（非单文件）也必须命中：三条不同性质的违规各一条。"""

    market = tmp_path / "market"
    market.mkdir()
    (market / "cross_submodule.py").write_text(
        "from app.db.engine import get_engine\n", encoding="utf-8"
    )
    (market / "reverse_dep.py").write_text("import app.strategy\n", encoding="utf-8")
    (market / "tests_import.py").write_text("from tests import conftest\n", encoding="utf-8")

    violations = scan_tree(tmp_path)

    assert len(violations) == 3
    assert {item.path for item in violations} == {
        "market/cross_submodule.py",
        "market/reverse_dep.py",
        "market/tests_import.py",
    }
