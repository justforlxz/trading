"""任务幂等键约定。

`job_key` = `job_name` + 参数规范化 JSON 的 sha256，落库时与 `job_name` 组成
`ops.job_run (job_name, job_key)` 唯一键（见 `docs/architecture/data-model.md` §1.3）。
规范化规则固定为：键排序、无多余空白、UTF-8、`ensure_ascii=False`，保证同一组
参数无论字典插入顺序如何都得到同一个键。
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_payload(payload: Mapping[str, Any] | None = None) -> str:
    """把任务参数序列化为稳定字符串。"""

    return json.dumps(
        payload or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def canonical_job_key(job_name: str, payload: Mapping[str, Any] | None = None) -> str:
    """返回任务幂等键（64 位十六进制）。"""

    if not job_name:
        raise ValueError("job_name must not be empty")
    material = f"{job_name}:{canonical_payload(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
