"""零 mock 门禁：生产代码不得出现 mock 语义标记、假数据文件或硬编码上游地址。

规划 §6.2 的三条硬检查全部落在这里：

1. `backend/app/**/*.py` 命中 mock 语义标记即失败；
2. `backend/app` 下不得有 `.json` / `.csv` 数据快照（mock 数据只能放 `backend/tests`）；
3. 生产代码不得出现字面量 http(s) URL，唯一例外是 `app/config.py`（配置默认值）。

标记口径按 PL 定稿（MKACG-707）：`fake|mock|dummy` 以「非字母数字」为边界，
因此 `_fake` / `fake_okx` 命中，`fake2` / `mockingbird` 不命中。
`sample` 与统计术语 `sample_size` 同形冲突，故对 `sample_size` 与复数 `samples`
显式放行，其余形态（`sample`、`sample_prices`、`"sample"`）仍然命中。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"

# fake/mock/dummy：字母数字算词内，下划线算边界（`fake_okx`、`_fake` 命中）。
_MOCK_WORDS = r"(?i)(?<![A-Za-z0-9])(?:fake|mock|dummy)(?![A-Za-z0-9])"
# sample：下划线算词内，仅放过统计术语 `sample_size` 与复数 `samples`。
_SAMPLE = r"(?i)(?<![A-Za-z0-9_])sample(?![sS]\b)(?!_size\b)"
# 本地回环与假 OKX server 端口：命中即说明生产代码连着本地假服务。
_LOCAL = r"localhost|127\.0\.0\.1|18080"
# 生产代码导入测试包（数据工厂/fixtures 都只在 tests 里）。
_TEST_IMPORT = r"\bfrom\s+tests\b|\bimport\s+tests\b"

FORBIDDEN = {
    "mock 语义标记": re.compile(_MOCK_WORDS),
    "sample 语义标记": re.compile(_SAMPLE),
    "本地地址/假服务端口": re.compile(_LOCAL, re.IGNORECASE),
    "测试包导入": re.compile(_TEST_IMPORT),
}

_HTTP_LITERAL = re.compile(r"(?i)^https?://")


@dataclass(frozen=True)
class Mark:
    """一次命中：定位到文件/行，并记录命中的规则与原文。"""

    path: str
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.text}"


def scan_source(source: str, *, path: str = "<memory>") -> list[Mark]:
    """逐行扫描一段源码。纯函数：负向用例直接喂构造字符串。"""

    marks: list[Mark] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for rule, pattern in FORBIDDEN.items():
            if pattern.search(line):
                marks.append(Mark(path, lineno, rule, line.strip()))
    return marks


def scan_tree(root: Path = APP_ROOT) -> list[Mark]:
    marks: list[Mark] = []
    for file in sorted(root.rglob("*.py")):
        marks += scan_source(
            file.read_text(encoding="utf-8"), path=file.relative_to(root).as_posix()
        )
    return marks


def _http_literals(file: Path) -> list[tuple[int, str]]:
    """文件里所有以 http(s):// 开头的字符串字面量（含 f-string 的常量片段）。"""

    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _HTTP_LITERAL.match(node.value)
    ]


# ------------------------------------------------------------------ 正向：真实代码


def test_app_tree_has_no_mock_markers() -> None:
    """`backend/app/**` 命中数必须为 0。"""

    marks = scan_tree()
    assert not marks, "\n".join(str(item) for item in marks)


def test_app_tree_ships_no_data_files() -> None:
    """生产代码不携带数据快照：`find backend/app -name '*.json'` 必须为空。"""

    data_files = sorted(
        path.relative_to(APP_ROOT).as_posix()
        for pattern in ("*.json", "*.csv")
        for path in APP_ROOT.rglob(pattern)
    )
    assert not data_files


def test_hardcoded_upstream_urls_live_only_in_config() -> None:
    """字面量 URL 只允许出现在 `app/config.py`（配置默认值）。"""

    problems: list[str] = []
    for file in sorted(APP_ROOT.rglob("*.py")):
        if file == APP_ROOT / "config.py":
            continue
        for lineno, value in _http_literals(file):
            problems.append(f"{file.relative_to(APP_ROOT).as_posix()}:{lineno}: {value}")
    assert not problems, "生产代码只允许从配置读取上游地址:\n" + "\n".join(problems)


# ------------------------------------------------------- 负向：构造的源码


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("fake_okx", "client = fake_okx()\n"),
        ("mock_transport", "transport = mock_transport()\n"),
        ("dummy_bar", "row = dummy_bar()\n"),
        ("_fake", "handler = _fake\n"),
        ("sample_prices", "prices = sample_prices\n"),
        ("localhost", 'URL = "http://localhost:8000"\n'),
        ("127.0.0.1", 'HOST = "127.0.0.1"\n'),
        ("18080", "PORT = 18080\n"),
        ("from tests", "from tests.factories import make_bar\n"),
    ],
)
def test_mock_markers_are_detected(name: str, source: str) -> None:
    assert scan_source(source), f"扫描器漏掉了 mock 标记:{name}"


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("out_of_sample", "flag = out_of_sample\n"),
        ("mockingbird", "bird = mockingbird\n"),
        ("fake2", "value = fake2\n"),
        ("sample_size", "def p_value(coefficient: float, sample_size: int) -> None: ...\n"),
        ("MIN_SAMPLES", "MIN_SAMPLES = 3\n"),
        ("samples", "# 样本数不足时返回 None(samples 太少)\n"),
    ],
)
def test_non_mock_identifiers_are_not_detected(name: str, source: str) -> None:
    assert not scan_source(source), f"{name} 被误判为 mock 标记"


def test_scan_tree_reports_marks_in_a_constructed_tree(tmp_path: Path) -> None:
    fake_pkg = tmp_path / "exchange"
    fake_pkg.mkdir()
    (fake_pkg / "client.py").write_text('BASE = "http://localhost:8000"\n', encoding="utf-8")
    (fake_pkg / "fixtures.py").write_text("DATA = load_dummy_bars()\n", encoding="utf-8")

    marks = scan_tree(tmp_path)

    assert {item.path for item in marks} == {"exchange/client.py", "exchange/fixtures.py"}
