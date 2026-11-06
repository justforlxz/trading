# ADR-0006：状态机放在「数据库状态列 + 领域纯函数 + 审计表」

- 状态：已接受
- 日期：2026-11-06
- 相关：`docs/architecture/data-model.md` §5、`docs/architecture/api-contract.md` §3.5、`docs/plan/p1.md` P1-15

## 上下文

策略有完整生命周期：`draft → pending_approval → approved / rejected → archived`。约束不止"合法迁移"，还包括：审批时必须绑定策略内容指纹（`content_hash`），内容变了旧审批失效；`approved` 后内容只读；每次迁移要留可追溯记录；非法迁移必须返回 409 而不是静默忽略。P1 只有这一台状态机；P2/P3 会新增订单与风险处置状态机。

## 决策

三件套：

1. **状态列**：`strategy.strategy.status` 是唯一真值，取值受 `CHECK` 约束。
2. **领域纯函数**：`backend/app/strategy/core/state_machine.py` 定义 `transition(current, action, context) -> next`，非法迁移抛领域异常（映射为 409）。它是唯一判定入口，API、job、脚本都必须调用它。
3. **审计表**：`strategy.strategy_transition` 追加记录 `from_status/to_status/at/actor/reason/request_id`，只写不改。

并发安全：迁移 SQL 带 `WHERE status = :expected`，影响行数为 0 即视为并发冲突，返回 409 `strategy_illegal_transition`。

## 后果

正面：

- 状态逻辑是纯函数，可穷举单测（5 个状态 × N 个动作的完整迁移矩阵），不需要起服务。
- 审计链可重放出当前状态，出现"状态漂移"时能定位到具体迁移与请求。
- 审批绑定 `content_hash`：内容修改后必须重新审批，杜绝"审批 A 回测 B"。

负面 / 代价：

- 状态机分散在三处（列约束、纯函数、审计表），需要保证三者一致；用单测覆盖"每个合法迁移都写一条审计"来兜底。
- 只能表达单实体状态流转；跨实体编排（例如"策略审批通过后自动创建回测并等待结果"）需要上层服务组合，状态机本身不提供。
- 长时间等待/超时升级（例如审批 7 天未处理自动过期）需要 cron 任务驱动，而不是状态机内建。

## 为什么不是其它方案

| 备选 | 拒绝理由 |
| --- | --- |
| 工作流引擎（Temporal / Camunda / 自建 BPMN） | 为一条 5 状态的生命周期引入额外服务、运维与学习成本；P1 没有并行分支、补偿事务、长事务的需求 |
| 数据库触发器实现迁移校验 | 逻辑停留在 SQL 里无法单测、无法在 API 层给出结构化错误（`details.from/to`），调试成本高 |
| 应用层各处 `if status == ...` 散落判断 | 状态会漂移：新增动作时漏改一处即产生非法状态，且无法回答"哪些迁移合法" |
| 事件溯源（只存事件，状态由重放得到） | 查询当前状态需要投影表，等于同时维护事件与投影；P1 的审计需求用追加表已满足 |

## 复核触发条件

出现以下任一需求时评估工作流引擎：跨天等待与超时升级、需要人工多级会签、需要补偿/回滚的分布式事务（P3 下单场景）、需要可视化流程编排。即使引入，`strategy_transition` 仍保留为业务审计。
