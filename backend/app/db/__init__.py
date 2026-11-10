"""数据库层：同步 SQLAlchemy 引擎 + PostgreSQL + 版本化迁移。

门面发布三样东西：迁移入口 `init_db`、声明基类 `Base`、工作单元 `session_scope`，
以及列类型 `DecimalText` / `UtcDateTime`。引擎实例与 `Session` 工厂仍是内部实现，
跨包只能经本门面使用（导入形态由架构测试强制）。
"""

from app.db.base import Base
from app.db.engine import session_scope
from app.db.init import init_db
from app.db.types import DecimalText, UtcDateTime

__all__ = ["Base", "DecimalText", "UtcDateTime", "init_db", "session_scope"]
