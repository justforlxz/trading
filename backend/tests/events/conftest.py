"""events 域测试装配：每个用例一个临时 schema，这里只负责执行迁移。

根 `conftest.py` 已把引擎指向本用例独有的 schema。
"""

import pytest

# 导入即注册表元数据（与 `app.main` 的装配路径一致）。
from app.alerts import AlertEventRow  # noqa: F401
from app.db import init_db
from app.events import NotificationDeliveryRow  # noqa: F401
from app.instrument import Instrument  # noqa: F401


@pytest.fixture(autouse=True)
def _events_schema() -> None:
    init_db()
