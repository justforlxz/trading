"""规范化 JSON 与指纹（纯函数）。

两枚指纹用途不同，不能互换：

- `strategy_key`：生成输入的幂等键，含构建器版本；同参数重复 POST 只留一条记录。
- `content_hash`：审批绑定的内容指纹，只含策略内容本身；审批记录引用它，
  内容一变旧审批自动失效。

规范化规则：键排序、无多余空白、Decimal 按十进制字符串输出、腿按标的内排序，
因此 JSON 键序与空白不影响结果。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

BUILDER_VERSION = "strategy-builder/1"


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _weight_text(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _weight_text(value: Any) -> str:
    """权重统一成 ``0.5`` / ``-0.25`` 这类最短十进制串，避免 0.5000000000 与 0.5 分叉。"""

    return format(Decimal(str(value)).normalize(), "f")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _leg_field(leg: Any, name: str) -> Any:
    if isinstance(leg, Mapping):
        return leg[name]
    return getattr(leg, name)


def leg_fingerprint(legs: Sequence[Any]) -> list[dict[str, Any]]:
    """只保留身份、方向与权重，按 `instrument_id` 排序，保证顺序无关。"""

    rows = [
        {
            "instrument_id": int(_leg_field(leg, "instrument_id")),
            "side": str(_leg_field(leg, "side")),
            "target_weight": _weight_text(_leg_field(leg, "target_weight")),
        }
        for leg in legs
    ]
    return sorted(rows, key=lambda row: row["instrument_id"])


def content_payload(
    *,
    kind: str,
    target_id: int | None,
    templates: Sequence[str],
    params: Mapping[str, Any],
    legs: Sequence[Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "target_id": target_id,
        "templates": list(templates),
        "params": dict(params),
        "legs": leg_fingerprint(legs),
    }


def content_hash(
    *,
    kind: str,
    target_id: int | None,
    templates: Sequence[str],
    params: Mapping[str, Any],
    legs: Sequence[Any],
) -> str:
    return digest(
        content_payload(
            kind=kind,
            target_id=target_id,
            templates=templates,
            params=params,
            legs=legs,
        )
    )


def strategy_key(
    *,
    kind: str,
    target_id: int | None,
    templates: Sequence[str],
    params: Mapping[str, Any],
    legs: Sequence[Any],
) -> str:
    return digest(
        {
            "builder_version": BUILDER_VERSION,
            "content": content_payload(
                kind=kind,
                target_id=target_id,
                templates=templates,
                params=params,
                legs=legs,
            ),
        }
    )


__all__ = [
    "BUILDER_VERSION",
    "canonical_json",
    "content_hash",
    "content_payload",
    "digest",
    "leg_fingerprint",
    "strategy_key",
]
