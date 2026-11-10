"""测试装配：TestClient 直连应用实例，不启动真实 uvicorn。

每个用例用独立的临时库文件，既避免污染 `backend/data/trading.db`，
也保证用例之间没有残留数据。
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.engine import get_engine
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把库文件指向临时目录；用完清掉配置与引擎缓存。"""

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "trading.db"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """会触发 lifespan（建表）的客户端。"""

    with TestClient(create_app()) as test_client:
        yield test_client
