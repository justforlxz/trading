"""ORM 声明基类。

P1 的实体从 S3 开始按 `docs/architecture/data-model.md` 落地；本文件只提供
Alembic `target_metadata` 的挂载点，不放任何表定义。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。"""
