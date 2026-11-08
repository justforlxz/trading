# ADR-0007：AI 助手是只读编排层，不是交易决策层

- 状态：已接受
- 日期：2026-11-08
- 相关：`docs/architecture/api-contract.md` §3.10、`docs/plan/p2-p4.md` §3 S11、`docs/reports/p4-acceptance.md`

## 上下文

P4 需要「市场与关系解释、策略与回测解读、自然语言查询、策略配置辅助」。语言模型擅长组织
文字，但也带来三类风险：

1. **事实漂移**：模型可能改写、编造数值，或把亏损解释成「应该加仓」。
2. **越权**：自然语言里可能夹带下单、改策略、改风控、审批、启动实盘的指令。
3. **不可复现**：同一问题重复调用可能得到不同答案，无法回溯当时依据。

项目原则是「AI Agent 不参与核心交易决策」，且所有交易决策必须可量化、可复现、可回测。
因此助手不能成为第二个决策入口，也不能成为交易域写操作的旁路。

## 决策

### 1. 分层：域服务算事实，`ai` 只编排

- 指标、关系系数、风控放行、持仓盈亏等全部由既有域服务/纯函数计算，`ai` 不重算。
- `ai` 读取域服务的只读结果，构造成 `citations[]`（每条带 `type`、`source` 与原始值），
  再把事实清单交给模型改写文案。
- 决策性计算只留在各域 `core` 纯函数里；`ai` 没有自己的指标实现。

### 2. 回答必须可核对

每个解释响应的 `citations[]` 记录本次实际读到的值，`source` 指向对应 GET 接口。测试逐项
比对 citations 与 GET 返回值（覆盖率、关系快照、策略 legs、回测 10 项指标），保证「看到的
解释」与「页面上的数字」同源。

### 3. 动作先判、许可后给：没许可就没有域数据

`/ai/query` 的处理顺序被固定成 **动作安全检查 → 正向读取许可 → 域端口调用**：

- **动作安全检查**：按标点切句后逐句判定，只用句首锚点（处置/祈使前缀或动作词根）识别祈使句。
  命中受控对象类别即 `403 ai_write_forbidden`；祈使但对象未分类则 `200 answerable=false`。
  任一句是祈使句，整句都不作答——「命令 + 为什么」不能靠追加问法变回只读。
- **正向许可**：只有疑问句才进入许可判定，且必须命中 `READ_PATTERNS`（关系/回测/策略/风控/
  持仓/行情）才放行；定义式问法由静态术语表作答。没有命中就是 `unlicensed`。
- **无法判断**：既不疑问也不祈使的输入一律 `unrouted`，同样不给数据。

关键点是「默认拒绝」：旧的「子串命中写词才拒绝、其余一律放行」会让没被枚举到的问法落到
`_facts_market` 兜底、把行情数据当回答发出去。改成正向许可后，漏判的代价从「泄露数据」变成
「拒绝回答」，方向正确。`general` 不再是可作答意图，兜底分支已删除。

### 4. 端口/适配器分层：`app.ai` 不认识任何业务域

`app.ai` 只依赖 `app.ports.ai_reads`（只有 Protocol 与 `AiReadsError`，零域 import）；
实现 `DomainAiReads` 放在 `app/adapters/domain/reads.py`，域异常统一转成
`AiReadsError(reason=...)`；装配入口 `build_ai_reads(session)` 在
`app/adapters/domain/registry.py`，由 `app/api/v1/ai.py`（组合根）调用。

这样「助手不能写业务域」不再只靠人review：`tests/ai/test_import_boundary.py` 用 AST 断言
`app.ai/**` 的 import 只在白名单内，`tests/ai/test_ports_readonly.py` 用 SQL 事件统计
业务表写入必须为 0，`tests/ai/test_risk_readonly.py` 用行数断言只读问答不新增
`risk.risk_policy` / `market.market_session` 行。

### 5. 只读路径不得为满足查询而写库

- 日历：`market` 端口只读 `list_sessions`，窗口内没数据就返回空列表，由助手给「数据不足」；
  不再调用 `sync_sessions`（那是 `GET /market/sessions` 的职责）。
- 风控：新增 `risk.service.resolve_policy_readonly`，缺省阈值用**未落库**的临时 `RiskPolicy`
  （`policy_version=None`、`policy_source="defaults"`），`status()` 改用它，不再
  `get_or_create_policy`。
- 审计 `ops.audit_log` 仍是唯一允许的写入；`app.ai` 用 SQLAlchemy Core 直接写该表，以守住
  import 白名单。

### 6. 默认关闭，降级必须显式

- 外部模型是可选依赖：`AI_ENABLED` 缺省 `false`、`AI_PROVIDER` 缺省 `none`，此时全部端点
  返回 `503 ai_not_configured` 且不发起外部请求。
- `rule_based` 路径不触网，响应必带 `degraded=true` 且 `model.provider="rule_based"`。
- 上游失败时按 `AI_FALLBACK_ENABLED` 决定降级还是 `502 ai_upstream_error`；模型输出若在亏损
  回测上建议加仓，服务端回退确定性摘要并置 `degraded=true`。

### 7. 审计复用 `ops.audit_log`，不新增迁移

每次调用写一条审计（含被拒与被降级的调用）：`actor="ai"`、`action` 形如
`ai.explain.backtest`、`resource/resource_id` 指向被解释实体、`after` 记模型、耗时、token 与
结果。`request_id + action` 组成幂等键，唯一索引保证重试不重复记账。P4 因此不需要 `0009` 迁移。

### 8. 策略建议只产草案

`suggest/strategy` 返回 `draft_only=true`、`persisted=false` 的草案，不写策略、不建 leg、不提交
审批。是否采纳由人工在策略编辑流程中决定。

## 后果

正面：

- 解释可核对：citations 与 GET 接口同源，测试可逐值断言。
- 助手无法越权：写意图在编排层被拒，且 `ai` 对交易域只有读依赖。
- 可回放：每条调用有审计，能回答「当时模型看到了什么、回答用了多久」。
- 无外部依赖也能跑：默认关闭 + 规则式路径让 CI 与离线环境完整验收。

负面 / 代价：

- 模型只能改写事实，回答的「洞察力」受限；复杂归因仍需各域提供更细的只读接口。
- 正向许可是**保守**的：没被 `READ_PATTERNS` 覆盖的问法（例如「策略 1 的调整历史」）会被判成
  `unrouted` 而拒绝作答，用户需要换成「解释策略 1 的调整历史」这类带疑问锚点的说法。这是用
  可用性换安全：漏判的代价从「多答一句」变成「少答一句」。
- 审计与解释不在同一事务内（解释是只读，审计独立提交），极端崩溃时可能少一条审计记录。

## 为什么不是其它方案

| 备选 | 拒绝理由 |
| --- | --- |
| 让模型直接查询数据库并自由作答 | 无法保证数值一致与可复现，且模型可读到不该暴露的字段 |
| 让模型调用执行域工具（function calling 下单） | 违背「AI 不参与核心交易决策」，无法通过风控与审批门禁 |
| 为助手单独建对话表与向量库 | P4 不需要跨会话记忆；新增存储与迁移没有对应验收价值 |
| 用 500 + 前端兜底展示错误 | 无法区分「未配置/越权/上游故障」，也破坏统一错误信封 |
| 把模型调用写进 `api` 层 | `api` 层直接依赖 httpx，无法用录制响应做无外网测试，违反 §4 边界 |

## 复核触发条件

出现以下需求时重新评估：需要多轮会话记忆、需要助手参与策略参数搜索、需要模型直接生成可
执行的策略配置、或需要把解释结论回写到决策流程。即使触发，也必须先通过人工审批与回测门禁，
助手仍不得直接下单或修改风控。
