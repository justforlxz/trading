"""数据库层：同步 SQLAlchemy 引擎 + SQLite（WAL）。

门面只发布建库入口 `init_db`；引擎、会话与声明基类是 db 的内部实现，
跨包不得直连 `app.db.engine` / `app.db.base`（导入形态由架构测试强制）。
"""

from app.db.init import init_db

__all__ = ["init_db"]
