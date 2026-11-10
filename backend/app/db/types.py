"""两类列类型：定点数与带时区时间。

金额与价格全仓用 `Decimal` 计算，落库统一走文本列。库里换成 `NUMERIC` 等于引入
第二套精度约定（库侧精度与 Python 侧的舍入不一致时，`0.01` 读回来就不再是
`0.01`）；时间列则统一存折算成 UTC 的无时区值，读出补回 UTC 时区。精度和时区
都是交易语义的一部分，不能在存取之间悄悄漂移。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import DateTime, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core import ValidationError

__all__ = ["DecimalText", "UtcDateTime"]


class DecimalText(TypeDecorator[Decimal]):
    """十进制文本列：绑定写字符串，读出还原 `Decimal`。"""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise ValidationError(f"定点数字段只接受 Decimal, 实际 {type(value).__name__}")
        return str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"库内定点数不是合法十进制:{value!r}") from exc


class UtcDateTime(TypeDecorator[datetime]):
    """UTC 时间列：绑定把带时区时间折算成 UTC 存无时区值，读出补回 UTC 时区。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValidationError("时间字段必须带时区")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
