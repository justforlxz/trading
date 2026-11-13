"""设置域的持久化模型：单行配置文档。

所有可编辑分组放在同一行里，`id` 固定为 1。分组以 JSON 文本保存，读回时由使用方
解析；这样新增或调整一个分组不需要为每一列单独写一次迁移。

交易所凭据只保存 `api_key`，且只写不读：接口永远只返回「是否已配置」与全掩码。
Secret 与 Passphrase 仍只经环境变量注入，不落库。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = ["SettingsRow"]


class SettingsRow(Base):
    """一份完整的设置文档。`id` 恒为 1，单行由服务层保证。"""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False)
    costs: Mapped[str] = mapped_column(Text, nullable=False)
    backtest: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    okx_api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
