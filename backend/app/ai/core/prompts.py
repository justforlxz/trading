"""提示词与事实清单: 只允许模型改写事实, 不允许新增未提供的数值。"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = (
    "你是自托管量化交易系统的只读分析助手。你只能依据用户消息中给出的事实清单作答, "
    "不得编造数值、标的或结论; 不得给出下单、改策略、改风控或启动实盘的指令; "
    "数据不足时明确说“数据不足”并列出缺失项; 回答使用简洁中文。"
)


def facts_block(citations: list[dict[str, Any]], *, title: str = "本次读取的事实") -> str:
    """把引用渲染成稳定的文本清单, 供模型改写 (引用本身不经过模型) 。"""

    lines = [f"{title} (共 {len(citations)} 条, 禁止改动其中数值) : "]
    for item in citations:
        payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
        lines.append(f"- {payload}")
    return "\n".join(lines)


__all__ = ["SYSTEM_PROMPT", "facts_block"]
