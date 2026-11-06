"""ops schema 的 ORM 模型：任务运行台账与审计日志。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "ops"


class JobRun(Base):
    """一次任务运行；(job_name, job_key) 唯一实现「同参数不重复执行」。"""

    __tablename__ = "job_run"
    __table_args__ = (
        UniqueConstraint("job_name", "job_key", name="uq_job_run_key"),
        Index("ix_job_run_status", "status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    job_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class AuditLog(Base):
    """关键写操作的审计日志（P1 无鉴权，actor 记为 anonymous）。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index(
            "uq_audit_log_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text, nullable=False, default="anonymous")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text)
