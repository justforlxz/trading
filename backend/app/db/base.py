"""ORM 声明基类：表定义随各自业务模块落地，本文件不放任何表。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类（`Base.metadata` 是建表入口）。"""
