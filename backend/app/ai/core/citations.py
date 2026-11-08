"""可复核引用: `type` 决定种类, 字段值必须来自本次实际读取。"""

from __future__ import annotations

from typing import Any


def citation(citation_type: str, source: str, **fields: Any) -> dict[str, Any]:
    return {"type": citation_type, "source": source, **fields}


__all__ = ["citation"]
