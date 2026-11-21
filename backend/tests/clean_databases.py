"""清理跑测试留下的临时数据库：`make test-clean`。

正常跑完由 conftest 的夹具删干净；进程被强杀（CI 超时、连按两次 Ctrl-C）时会留下
`trading_test_*` 用例库与 `trading_tmpl_<进程号>` 模板库，这个脚本按前缀把它们删掉。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 模块都在 backend/ 下：`make test-clean` 以 backend 为工作目录，但这个脚本也应该能
# 从别的工作目录直接跑，因此显式补上 backend/，不依赖 cwd。
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _apply_default_database_url() -> None:
    """执行 `backend/conftest.py`：它在缺 `DATABASE_URL` 时补上本地默认地址。

    按路径加载而不是 `import conftest`：`tests/conftest.py` 同名，从别的工作目录运行时
    会被它抢先命中。
    """

    spec = importlib.util.spec_from_file_location(
        "_trading_root_conftest", _BACKEND_DIR / "conftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


_apply_default_database_url()

from app.config import get_settings  # noqa: E402
from tests.db_admin import (  # noqa: E402
    TEMPLATE_DATABASE_PREFIX,
    TEST_DATABASE_PREFIX,
    drop_databases_starting_with,
    maintenance_engine,
)


def main() -> None:
    """删掉所有测试数据库，把删掉的库名打到 stdout。"""

    get_settings.cache_clear()
    engine = maintenance_engine(get_settings().database_url)
    try:
        dropped = drop_databases_starting_with(
            engine, TEST_DATABASE_PREFIX, TEMPLATE_DATABASE_PREFIX
        )
    finally:
        engine.dispose()

    for name in dropped:
        print(f"test-clean: 已删除 {name}")
    print(f"test-clean: 共删除 {len(dropped)} 个测试数据库")


if __name__ == "__main__":
    main()
