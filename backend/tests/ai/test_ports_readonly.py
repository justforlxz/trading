"""P4-03: 只读门禁 —— `/ai/*` 不产生业务域写入, 拒答请求不调用读端口。

两层证据:

1. SQL 层: `before_cursor_execute` 统计 INSERT/UPDATE/DELETE, 排除 `ops.audit_log`
   (审计是唯一允许的写入); `before_flush` 统计 ORM 新增/脏对象, 同样排除审计行。
2. 端口层: 把 `build_ai_reads` 换成「一调用就失败」的记录型对象, 证明写操作与
   未许可输入在访问域数据之前就被拦截 (端口调用次数为 0)。
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as OrmSession

from tests.ai.conftest import seed_full_backtest, seed_relations, seed_target

WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE")
AUDIT_TABLE = "ops.audit_log"


def _is_business_write(statement: str) -> bool:
    head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
    if head not in WRITE_KEYWORDS:
        return False
    return AUDIT_TABLE not in statement.lower()


class WriteRecorder:
    """统计业务写: 审计表以外的 INSERT/UPDATE/DELETE 与 ORM 脏对象。"""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.orm_writes: list[str] = []
        self._engine = None
        self._cursor_listener = None
        self._flush_listener = None

    def reset(self) -> None:
        self.statements.clear()
        self.orm_writes.clear()

    def start(self, engine: Any) -> None:
        self._engine = engine

        def _before_cursor_execute(
            conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: Any
        ) -> None:
            if _is_business_write(statement):
                self.statements.append(statement)

        def _before_flush(session: Any, flush_context: Any, instances: Any) -> None:
            for obj in (*session.new, *session.dirty, *session.deleted):
                if type(obj).__name__ == "AuditLog":
                    continue
                self.orm_writes.append(type(obj).__name__)

        self._cursor_listener = _before_cursor_execute
        self._flush_listener = _before_flush
        event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(OrmSession, "before_flush", _before_flush)

    def stop(self) -> None:
        if self._engine is not None and self._cursor_listener is not None:
            event.remove(self._engine.sync_engine, "before_cursor_execute", self._cursor_listener)
        if self._flush_listener is not None:
            event.remove(OrmSession, "before_flush", self._flush_listener)
        self._engine = None


@pytest.fixture
def write_recorder(database_url: str) -> Any:
    from app.db import session as db_session

    recorder = WriteRecorder()
    recorder.start(db_session.engine)
    try:
        yield recorder
    finally:
        recorder.stop()


async def test_all_ai_endpoints_do_not_write_business_rows(
    client: AsyncClient,
    session: AsyncSession,
    configure_ai,
    write_recorder: WriteRecorder,
) -> None:
    target = await seed_target(session, symbol="AAPL")
    await seed_relations(session, target_id=target.target_id)
    seeded = await seed_full_backtest(session)
    configure_ai()

    write_recorder.reset()
    calls: tuple[tuple[str, dict[str, Any]], ...] = (
        ("/api/v1/ai/explain/market", {}),
        ("/api/v1/ai/explain/relations", {"target_id": target.target_id}),
        ("/api/v1/ai/explain/strategy", {"strategy_id": seeded.strategy_id}),
        ("/api/v1/ai/explain/backtest", {"run_id": seeded.run_id}),
        ("/api/v1/ai/query", {"question": "解释一下当前行情"}),
        ("/api/v1/ai/suggest/strategy", {"target_id": target.target_id}),
    )
    for path, body in calls:
        response = await client.post(path, json=body)
        assert response.status_code == 200, (path, response.text)
        assert response.json()["read_only"] is True

    assert write_recorder.statements == []
    assert write_recorder.orm_writes == []


class RecordingReads:
    """任何端口方法被访问都记一笔并立即失败。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def _reject(*args: Any, **kwargs: Any) -> None:
            self.calls.append(name)
            raise AssertionError(f"域数据端口在许可判定前被调用: {name}")

        return _reject


@pytest.mark.parametrize(
    "question",
    [
        "帮我下单买入 AAPL 100 股",  # 写: 403
        "把杠杆拉到5倍",  # 写: 403
        "请问今天天气如何",  # 未许可: 200 answerable=false
        "今天天气怎么样",  # 无法判断: 200 answerable=false
    ],
)
async def test_refused_requests_never_touch_read_ports(
    client: AsyncClient,
    configure_ai,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    from app.adapters.domain import registry

    fake = RecordingReads()
    configure_ai()
    monkeypatch.setattr(registry, "build_ai_reads", lambda session: fake)

    response = await client.post("/api/v1/ai/query", json={"question": question})
    assert response.status_code in {200, 403}, response.text
    if response.status_code == 200:
        assert response.json()["answerable"] is False
        assert response.json()["citations"] == []
    assert fake.calls == []
