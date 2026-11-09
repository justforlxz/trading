"""MCP 服务：把 P1-P3 能力以 Model Context Protocol 暴露给外部 Agent。

本项目不含任何 LLM、不做自然语言意图理解、不生成结论文字；这里只做
「协议解析 -> 既有 service 调用 -> 结构化结果」以及鉴权、scope 与审计。
决策依据见 `docs/adr/0007-mcp-instead-of-agent.md`。
"""
