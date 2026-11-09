# ADR-0007：P4 用 MCP 服务取代内置 AI Agent

- 状态：已接受
- 日期：2026-11-09
- 相关：`docs/plan/p2-p4.md` §3（原 S11 条目被本 ADR 取代）、`docs/mcp.md`、`docs/architecture/data-model.md` §10

## 上下文

P4 原计划是一个**内置** AI 助手（`p2-p4.md` 的 P4-01 ~ P4-07）：LLM 适配层、市场/关系/策略/回测的
解释生成、自然语言查询、写意图分类器、AI 面板。落地时会带来三个结构性问题：

1. **结论文字不可复核**。模型生成的解释既不是规则算出来的，也无法回测；一旦与账本不一致，
   排查只能重新跑一次模型，同一输入两次输出不同。
2. **写意图分类器是安全边界上的猜测**。「这句话是不是下单指令」用分类器判定，误判的代价是
   真实的资金操作。把授权交给统计模型，等于把最不能出错的一环交给最不可控的部分。
3. **依赖与运维成本**。引入 LLM SDK、密钥、限流与外部网络依赖，却与 P1-P3 的既定职责
   （行情、研究、策略、风控、执行）没有任何交集。

同时，外部 Agent（Claude Desktop / 自建 agent / IDE 插件）已经具备推理与编排能力。系统
真正缺的不是「又一个会说话的界面」，而是**一个把既有能力安全暴露出去的标准协议面**。

## 决策

P4 交付一个 **MCP server**（Model Context Protocol，JSON-RPC 2.0 over HTTP），
`p2-p4.md` §3 的 P4-01 ~ P4-07 全部取消，改为：

1. **协议面**：FastAPI 内挂 `POST /mcp`（Streamable HTTP，JSON 与 SSE 双形态）；
   另有 `trading-mcp` stdio 包装器，仅做 HTTP 转发。
2. **鉴权与 scope**：`mcp.mcp_clients`（`token_hash` 只存 sha256、`scopes`、`revoked_at`）+
   `read` / `operate` 两级 scope；Token 只生成时明文返回一次。
3. **工具面**：只读查询 + 受控操作，**不含**裸下单、审批、实盘授权、改风控阈值。
4. **受控执行**：执行闸门与 `risk_status` 同源（含回撤 breach），有符号权重按绝对值校验；`execute_strategy_action` 必须依次通过「实盘授权 → 未暂停 → 风控放行 →
   幂等校验」四道闸门，任一失败即拒绝并写 `mcp.mcp_call_log`（带 `reason`）。
5. **审计**：每次调用落 `mcp.mcp_call_log`；参数只留 sha256 摘要。

服务端**不含任何 LLM**：不解析自然语言、不生成结论、不参与交易决策。

## 后果

正面：

- 消除「模型生成结论」这一不可复核环节；所有对外数据都来自既有 service 的确定性输出。
- 安全边界回到**结构性约束**而不是判断：工具清单里没有 `place_order` / `approve_strategy` /
  `live_authorize` / `set_risk_limit` / `toggle_live_trading`，外部 Agent 无从取得这些能力
  （由 `tests/mcp/test_tools_consistency.py` 对 `tools/list` 负向断言兜底）。
- 一个字段一份实现：`get_strategy` 与 `GET /api/v1/strategies/{id}` 共用
  `app.strategy.service.strategy_detail`，并由 pytest 逐项比对，杜绝两套序列化漂移。
- 每次调用可审计（客户端、工具、状态、错误码、原因、耗时），越权尝试留痕。

负面 / 代价：

- 需要外部 Agent 才能真正「问答」；本项目不提供对话界面，这是刻意取舍。
- 工具面是一份需要长期维护的契约：新增能力要同步 schema、scope、文档与测试。
- 同步执行 `trigger_scan` 让单次调用可能较慢（受扫描规模影响）；换来的是调用方立即拿到结果。
- 运行暂停用 `strategy.paused_at` 一列表达，而不是新增策略状态：`status` 的五值状态机保持
  不变，但这意味着 Web 端暂时没有暂停开关，只有 MCP 能写这一列。

## 为什么不是其它方案

| 备选 | 拒绝理由 |
| --- | --- |
| 保留内置 AI 助手（原 P4-01~P4-07） | 结论文字不可回测、不可复核；写意图分类器把授权交给统计模型；引入 LLM 依赖却与核心账本无关 |
| 直接对外开放 REST（复用 `/api/v1`） | 无客户端级 scope、无逐工具审计；且外部 Agent 需要自行理解业务语义，等于把编排复杂度外推而非收敛 |
| 只做 CLI 脚本 | 没有鉴权与审计边界，无法区分「哪个 Agent 做了什么」，也无法按客户端吊销 |
| 在 MCP 里提供 `place_order` 等裸操作 | 订单将脱离策略归属，风控闸门与幂等校验都会被绕过；这与「所有订单必须归属策略」的既定边界冲突 |
| 让 MCP 直接写库（绕过 service） | 会把状态机、幂等与审计拆成两套实现，很快产生不一致 |

## 复核触发条件

- 出现需要在 Web 上人工暂停/恢复策略的需求 → 为 `paused_at` 补 API 与 UI，而不是让 MCP 独占。
- 外部 Agent 需要的能力超出了既有 service（例如组合调仓审批）→ 先补业务与人工审批流程，
  再决定是否暴露工具；不允许用 MCP 工具绕过审批。
- 需要多租户或按工具细粒度授权 → 在 `scopes` 上扩展（例如 `read:orders`），
  但不得引入「授权类」工具。
