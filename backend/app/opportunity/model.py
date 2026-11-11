"""机会发现的持久化模型：`opportunities` 表。

一行是一条「值得做、往哪个方向做」的候选记录：模式、锚点、判定时刻、综合分数、
候选腿、判定依据与审核状态。两个 JSON 文本列分开存，是因为它们是两件事：

- `evidence` 是判定依据（相关系数、广度、共振强度等），原样透传给前端，不在契约层
  二次解释；
- `legs` 是候选本身（哪个标的、往哪个方向、自身强度多少）。契约的
  `Opportunity.legs` 要求逐条给出，而回看一条机会时不允许拿当下的行情重算一遍
  （那已经不是同一条机会了），因此腿随机会一起落库。

`opportunity_id` 由内容派生（模式 + 锚点 + `as_of` + 腿），同一份输入重复检测得到
同一个标识，重复执行因此是幂等的；状态是人工审核的结论，重跑检测不会覆盖它。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalText, UtcDateTime

__all__ = ["OpportunityRow"]


class OpportunityRow(Base):
    """一条机会记录；`mode` 是 `target` / `market`，`status` 见服务层的状态机。"""

    __tablename__ = "opportunities"

    opportunity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    anchor_product_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    as_of: Mapped[datetime] = mapped_column(UtcDateTime)
    score: Mapped[Decimal] = mapped_column(DecimalText)
    legs: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
