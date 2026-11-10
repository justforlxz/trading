"""数据库层：同步 SQLAlchemy 引擎 + SQLite（WAL）。

不在此处导出引擎或会话，调用方按需 `from app.db.engine import ...`，
避免导入包时建连。
"""
