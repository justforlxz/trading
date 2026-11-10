"""架构门禁：类别分支只允许出现在 `instrument` / `exchange` / `execution` 三个目录。

类别差异（现货与永续的交易规则不同）必须集中在标的模块的一处定义里。别处一旦
自己写 `inst_type == "SPOT"` 之类的分支，接入第三种类别时就得挨个文件去找、去改，
漏一处就是一处静默错误。本门禁把「只在一处定义」变成会红的测试。

判定口径：

- 只看比较运算 `==` / `!=` / `in` / `not in`；`inst_type is None`、`if inst_type:`
  这类判空与真值判断不是类别分支，不算命中。
- 命中的形状是「`inst_type` 与一个类别取值比较」。两个运行期 `inst_type` 之间的
  比较（例如按请求参数过滤 `row.inst_type == inst_type`）不构成类别分支，不算命中。
- 命中位置落在白名单目录之外即失败，失败信息给出文件与行号。

负向用例用构造的源码驱动同一个扫描器，因此「扫描器坏了」与「代码违规了」不会混成
同一个红。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"

#: 允许按类别分支的目录（`backend/app/` 下的目录名）。放宽这里必须先改测试，
#: 使改动在评审里显式可见。
ALLOWED_DIRS: tuple[str, ...] = ("instrument", "exchange", "execution")

#: 参与判定的比较运算符。
COMPARISONS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.In: "in",
    ast.NotIn: "not in",
}

INST_TYPE = "inst_type"


@dataclass(frozen=True)
class Violation:
    """一处越界的类别分支。"""

    path: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


def _is_inst_type(node: ast.expr) -> bool:
    """`inst_type` 或 `row.inst_type` 这类取标类别名的表达式。"""

    if isinstance(node, ast.Name):
        return node.id == INST_TYPE
    return isinstance(node, ast.Attribute) and node.attr == INST_TYPE


def _is_allowed(relative: Path) -> bool:
    return bool(relative.parts) and relative.parts[0] in ALLOWED_DIRS


def scan_source(source: str, *, path: str = "<memory>") -> list[Violation]:
    """扫描一段源码里的类别分支。纯函数：不落盘、不 import。"""

    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for index, op in enumerate(node.ops):
            symbol = COMPARISONS.get(type(op))
            if symbol is None:
                continue
            left, right = operands[index], operands[index + 1]
            if not (_is_inst_type(left) or _is_inst_type(right)):
                continue
            if _is_inst_type(left) and _is_inst_type(right):
                continue  # 两个运行期类别之间比较：不是在按类别分支
            expression = ast.unparse(node)
            violations.append(
                Violation(
                    path,
                    node.lineno,
                    f"`{expression}` ({symbol}) 在 {_allowed_text()} 之外按类别分支",
                )
            )
    return violations


def scan_tree(root: Path = APP_ROOT) -> list[Violation]:
    """扫描整棵 `app/` 树，只报告白名单目录之外的命中。"""

    violations: list[Violation] = []
    for file in sorted(root.rglob("*.py")):
        relative = file.relative_to(root)
        if _is_allowed(relative):
            continue
        violations += scan_source(
            file.read_text(encoding="utf-8"),
            path=(Path("app") / relative).as_posix(),
        )
    return violations


def _allowed_text() -> str:
    return " / ".join(f"app/{name}/" for name in ALLOWED_DIRS)


# ------------------------------------------------------------------ 正向：真实代码


def test_app_tree_has_no_category_branch_outside_allowed_dirs() -> None:
    """`backend/app/**` 零越界；红时逐条打印文件/行/原因。"""

    violations = scan_tree()
    assert not violations, "\n".join(str(item) for item in violations)


def test_allowed_dirs_are_exactly_three() -> None:
    """白名单不能为了变绿而被悄悄放宽：加目录必须改这里，评审里看得见。"""

    assert ALLOWED_DIRS == ("instrument", "exchange", "execution")


# ------------------------------------------------------ 负向：构造的违规源码


@pytest.mark.parametrize(
    ("reason", "source"),
    [
        ("与类别字面量相等比较", 'if inst_type == "SPOT":\n    pass\n'),
        ("与类别常量不相等比较", "if row.inst_type != SWAP:\n    pass\n"),
        ("与类别集合成员判断", 'if row.inst_type in {"SPOT", "SWAP"}:\n    pass\n'),
        ("与类别集合非成员判断", "if inst_type not in INST_TYPES:\n    pass\n"),
    ],
)
def test_scanner_flags_constructed_category_branches(reason: str, source: str) -> None:
    violations = scan_source(source)

    assert len(violations) == 1, f"扫描器漏掉或重复报告:{reason}"
    assert violations[0].line == 1
    assert "按类别分支" in violations[0].reason


@pytest.mark.parametrize(
    ("reason", "source"),
    [
        (
            "两个运行期类别之间的过滤",
            "if inst_type is None or row.inst_type == inst_type:\n    pass\n",
        ),
        ("判空比较", "if inst_type is None:\n    pass\n"),
        ("真值判断", "if inst_type:\n    pass\n"),
        ("与类别无关的比较", 'if row.symbol == "SPOT":\n    pass\n'),
        ("不做比较的取值", "rules = trading_rules(row.inst_type)\n"),
    ],
)
def test_scanner_accepts_non_category_comparisons(reason: str, source: str) -> None:
    assert scan_source(source) == [], f"{reason} 被误判"


def test_scan_tree_skips_allowed_dirs_and_reports_the_rest(tmp_path: Path) -> None:
    """树扫描：`exchange/` 里的命中放过，`market/` 里的命中必须报出来。"""

    app = tmp_path / "app"
    for name, source in (
        ("market", 'if inst_type == "SPOT":\n    pass\n'),
        ("exchange", 'if inst_type == "SPOT":\n    pass\n'),
        ("instrument", "if inst_type == SWAP:\n    pass\n"),
    ):
        package = app / name
        package.mkdir(parents=True)
        (package / "probe.py").write_text(source, encoding="utf-8")

    violations = scan_tree(app)

    assert len(violations) == 1
    assert violations[0].path == "app/market/probe.py"
    assert violations[0].line == 1
