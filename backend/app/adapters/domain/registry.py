"""助手只读端口的装配入口。

组合根在 `app/api/v1/ai.py`：它把当前请求的会话交给本函数，拿到 `AiReads` 后
传给 `app.ai.service`。`app.ai` 因此不需要 import 任何域模块或适配器。
"""

from __future__ import annotations

from app.adapters.domain.reads import DomainAiReads
from app.db.session import AsyncSession
from app.ports.ai_reads import AiReads


def build_ai_reads(session: AsyncSession) -> AiReads:
    return DomainAiReads(session)


__all__ = ["build_ai_reads"]
