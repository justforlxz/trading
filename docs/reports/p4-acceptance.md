# P4 分析助手验收报告（MKACG-702 / S11）

**结论：P4 只读分析助手交付完成。真实交易保持关闭，助手全程未调用任何交易域写接口，外部模型默认关闭。**

## 1. 环境与前置

| 项 | 值 |
| --- | --- |
| 运行日期 | 2026-11-08（UTC） |
| 仓库基线 | `master@6953eb8`（MKACG-701 P3 交易执行合并后） |
| 数据库迁移 | `0008_execution_schema (head)`；P4 未新增迁移，审计复用 `ops.audit_log` |
| 运行形态 | Docker Compose 六服务（`postgres`/`redis`/`api`/`worker`/`scheduler`/`web`） |
| 助手开关 | `AI_ENABLED=false`（缺省）；冒烟验收临时切 `AI_PROVIDER=rule_based`，不访问网络 |
| 外部模型 | 未配置（`AI_MODEL`/`AI_BASE_URL`/`AI_API_KEY` 均为空） |
| 执行模式 | `GET /api/v1/execution/mode` → `mode=paper`，`real_trading_enabled=false` |

规则式（`AI_PROVIDER=rule_based`）回答由本次实际读取的事实摘要直接生成，响应固定
`degraded=true` 且 `model.provider="rule_based"`，不会访问任何外部模型服务。

## 2. 一键验收（`bash scripts/e2e/p4_smoke.sh`）

退出码 0。逐步耗时（同一台机器、同一 compose 栈）：

| 步骤 | 内容 | HTTP | 耗时(ms) | 结论 |
| --- | --- | --- | --- | --- |
| 0 | 预检：健康、迁移版本、真实交易关闭、AI 规则式可用 | 200 | 1546 | 迁移 `0008_execution_schema (head)`；mode=paper；provider=rule_based |
| 1 | 幂等播种：验收目标、关系快照、已审批策略、回测指标 | n/a | 2232 | `target_id=8`，`strategy_id=22`，`run_id=22` |
| 2 | 解释市场：`POST /ai/explain/market` 与覆盖接口逐项一致 | 200 | 168 | coverage 四字段与 `GET /market/coverage` 一致；同 request_id 重放 |
| 3 | 解释关系：citations 与 `GET /targets/{id}/relations` 一致 | 200 | 67 | `snapshot_id`、边系数、最优滞后逐项一致 |
| 4 | 解释策略：legs 与 `GET /strategies/{id}` 一致 | 200 | 48 | 2 条腿的 inst_id/side/weight 一致 |
| 5 | 解读回测：10 项指标与 `GET /backtests/{id}/metrics` 逐项一致 | 200 | 55 | 10 项指标完全相等；亏损回测无加仓建议 |
| 6 | 只读问答语料：`POST /ai/query`（answered / unlicensed 按允许集合断言） | 200 | 34 | 语料 15 条只读/拒答用例逐条通过；拒答不带引用 |
| 7 | 写意图边界：语料中的 forbidden 用例不产生订单 | 403 | 58 | 18 条写用例全部被拒（403 或 200 answerable=false）；订单数不变 |
| 8 | 审计：每次调用一条 `ops.audit_log`，重放不重复 | 200 | 196 | 6 个请求 6 条审计；market 重放未重复记账 |

验收产物：`docs/reports/p4-smoke-artifacts.json`。

> 上表是 P4 交付时的冒烟记录。MKACG-702 架构改造后，步骤 6/7 改为读取 `backend/tests/ai/data/query_cases.json`（answered/unlicensed/forbidden 按允许集合断言）；改造后已整条重跑：exit 0，9 步全过，步骤 6 的 23 条只读/拒答语料中 20 条作答，步骤 7 的 74 条写语料全部被拒且订单数不变。

## 3. 出口门禁

```bash
make lint && make test && make coverage
bash scripts/e2e/p4_smoke.sh
```

| 命令 | 结果 |
| --- | --- |
| `make lint` | 通过（ruff check / ruff format --check 全绿；前端 eslint 0 error，3 个既存 warning） |
| `make test` | 通过：**767 passed**，前端 `tsc --noEmit && vite build` 成功 |
| `make coverage` | 通过：**767 passed**，总覆盖率 **80.04%**（门槛 70%，未下调） |
| `bash scripts/e2e/p4_smoke.sh` | 退出码 0（9 步全通过） |
| `pytest -q backend/tests/ai` | **168 passed**（全部使用假适配器/录制响应，无外网） |
| `rg -n 'place_order\|cancel_order\|create_order' backend/app/ai` | 0 命中 |
| `rg -n 'from .*execution\|import .*execution' backend/app/{market,strategy,risk,backtest}` | 0 命中 |
| `rg -n 'INSERT\|UPDATE' backend/app/ai` | 0 命中（审计是唯一写入；改造后经 Core `insert(ops.audit_log)`） |
| `rg -n 'import httpx' backend/app/api` | 0 命中 |

上表 744 passed / 80.08% 是 MKACG-702 架构改造后重跑的全量结果。MKACG-702 架构改造轮次在
`agent/agent/5e7d3496ba8c` 上只跑了限定门禁（全量 pytest 约 48 分钟，按裁决不重跑）：

| 命令 | 结果 |
| --- | --- |
| `docker compose --profile dev run --rm --no-deps api-dev ruff check app tests` | 通过 |
| `docker compose --profile dev run --rm --no-deps api-dev ruff format --check app tests` | 通过（225 files already formatted） |
| `pytest -q tests/ai tests/test_ai_query_intent.py` | **329 passed**（15m27s） |
| `pytest -q tests/ai/test_import_boundary.py` | 2 passed：`app.ai` 的 import 白名单（AST）+ `app/adapters/domain/reads.py` 存在 |
| `pytest -q tests/ai/test_ports_readonly.py` | 5 passed：6 个端点业务写为 0；写/未许可/未识别请求端口调用为 0 |
| `pytest -q tests/ai/test_risk_readonly.py` | 2 passed：问风控前后 `risk.risk_policy` 行数不变；问市场前后 `market.market_session` 行数不变 |
| `pytest -q tests/ai/test_query_corpus.py` | 33 passed：语料 `backend/tests/ai/data/query_cases.json` 逐条按允许结果集合断言 |

## 4. 逐条 AC 对照

| # | AC | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 全量 pytest 通过；`make lint`/`make test`/`make coverage` 全绿；覆盖率 ≥70% | ✅ | 本文 §3：全量 **767 passed**，覆盖率 **80.04%**；架构改造限定门禁（`tests/ai` + `test_ai_query_intent.py`）**329 passed** |
| 2 | `alembic upgrade head` 幂等；未新增迁移需说明复用 `ops.audit_log` 的理由 | ✅ | 迁移仍为 `0008_execution_schema`；审计直接写既有 `ops.audit_log`（字段 `actor`/`action`/`resource`/`resource_id`/`after`/`idempotency_key` 足够承载），避免为单表新增迁移 |
| 3 | 未配置时 6 个 `/ai/*` 端点全部 503，且零外部请求 | ✅ | `tests/ai/test_guard.py`：`AI_ENABLED=true, AI_PROVIDER=none` 时 6 端点均 503 `ai_not_configured`；把适配器构造换成「访问即失败」仍返回 503，审计 0 行 |
| 4 | `pytest -k adapter` 无外网通过 | ✅ | `tests/ai/test_adapter.py`：`httpx.MockTransport` 覆盖 OpenAI 成功/500/坏 JSON/空内容/超时；rule_based 适配器不触网 |
| 5 | market/relations citations 与实际接口逐项一致 | ✅ | `tests/ai/test_explain.py` 对 `GET /market/coverage`、`GET /market/sessions`、`GET /targets/{id}/relations` 逐字段比较；冒烟步骤 2、3 |
| 6 | 回测 10 项指标逐项一致；亏损回测不得出现加仓/扩大仓位结论 | ✅（双保险） | `test_explain.py` 断言 10 项 name/value 完全相等；假模型录制返回「建议加仓并扩大仓位」时被 `GROWTH_ADVICE_TERMS` 拦截并回退摘要（`degraded=true`）；冒烟步骤 5 再做负向 grep |
| 7 | 无数据 → 明确「数据不足」+缺失项；不存在的实体 → 404 而非 500 | ✅ | `test_explain.py`：无 targets → `missing=["market_coverage"]`；无关系快照 → `missing=["relations_snapshot"]`；未知 target/strategy/run → 域错误码 404 |
| 8 | 写操作/未许可/未识别都不产生数据回答 | ✅ | 契约允许两种合法结果（403 或 200 `answerable=false`），误拒可接受、漏答不可； 处理顺序固定为「动作安全检查 → 正向读取许可 → 域端口调用」，前两步未通过时端口调用为 0。`app/ai/core/query.py::assess()` 只用句首/句末锚点：祈使句命中受控对象类别即 403 `ai_write_forbidden`（`error.details.refusal = {code, message, matched_object_class}`）；祈使未分类 / 未许可 / 无法判断一律 200 `answerable=false` + `citations=[]` + `reason`，不含任何域数据。证据：`tests/ai/test_query_corpus.py` 97 条语料（本轮 10 条动作、7 条只读概念/状态、10 条「祈使 + 问号/吗/好吗/怎么样」交叉用例、10 条「把 X 的 Y + 变更形态」、10 条「对象 + 的 + 属性 + 动作」、8 条「是/有/多少/有几 + 变更动词」、8 条「句首变更谓词 + 对象属性」泄漏用例、8 条只读误拒回归、9 条「读动词 + 变更」泄漏用例（解释/强调/假设/介绍/评估/对比/查看/列出/解读 + 腿/仓位 + 合并/清掉/作废/下线/减半/删除/改成/减少/清空）、历轮写/读代表用例，含换行绕过与 `approve strategy 1`）逐条按允许集合断言；`tests/ai/test_guard.py` 38 条端到端（403 + details + 审计）；`tests/test_ai_query_intent.py` 161 条纯函数矩阵，其中 `test_action_check_always_precedes_attribute_structure` 以 432 种组合锁住「动作检查必须先于属性结构/问句」，`test_object_first_change_never_answerable` 以 4 主体 × 4 属性 × 8 变更 × 7 结尾（含「是两条/有多少/有几条」）共 896 组锁住「属性结构不能单独换来许可」；尾段判定要求「剥掉谓词与量词后必须为空，且不得含任何变更形态」，`策略 1 的腿是两条改成一条` 等 7 条阻断样例均 403；`tests/ai/test_ports_readonly.py` 用记录型端口证明拒答请求端口调用为 0；`scripts/e2e/p4_smoke.sh` 步骤 6/7 读取同一份语料 |
| 9 | `suggest` 不落库，响应 `draft_only=true` | ✅ | `tests/ai/test_suggest.py`：草案前后 `strategy`/`strategy_leg`/`strategy_approval` 计数不变，响应 `draft_only=true`、`persisted=false` |
| 10 | 成功与被拒调用各一条审计；`actor='ai'`；同 `idempotency_key` 不重复 | ✅ | `test_guard.py`：回测解释审计 1 行（action/resource/resource_id/model/latency 全断言）；写意图 1 行 `outcome=forbidden`；同 request_id 重放仍 1 行。冒烟步骤 8 用 SQL 复核 6 请求 6 条 |
| 11 | `ai` 无下单符号；其他域不 import execution；`ai` 只写 `ops.audit_log` | ✅ | `rg -n 'place_order|cancel_order|create_order' backend/app/ai` 0 命中；反向依赖 0 命中；`tests/ai/test_import_boundary.py` 证明 `app.ai` 不 import 任何业务域；`tests/ai/test_ports_readonly.py` 证明业务表写为 0（审计经 Core `insert(ops.audit_log)`，是唯一写入） |
| 12 | 前端 `/assistant` 可提问、展示答案与引用、写意图被拒提示；lint/build 通过 | ✅ | `frontend/src/pages/assistant/index.tsx`（纯展示，不计算指标）；`pnpm lint` 0 error；`vite build` 成功 |
| 13 | `p4_smoke.sh` 退出 0，覆盖 7 类场景，失败非 0 并打印失败步骤 | ✅ | 本文 §2；脚本 `fail()` 输出步骤名并以 1 退出 |
| 14 | `mode=real` 订单数保持 0；未配置 `REAL_TRADING_ENABLED` 下单仍 403 | ✅ | 冒烟步骤 0 断言 `mode=paper`、`real_trading_enabled=false`；步骤 7 前后订单条数不变。P3 的真实下单门禁未改动 |
| 15 | `api-contract §3.10`、ADR 0007、本报告 | ✅ | `docs/architecture/api-contract.md §3.10`；`docs/architecture/adr/0007-ai-assistant-boundary.md`；本文 |

## 5. 分层与红线自检

本轮新增三条自动化门禁，把「只读」从人工 review 变成可执行断言：

| 门禁 | 文件 | 断言 |
| --- | --- | --- |
| import boundary | `tests/ai/test_import_boundary.py` | AST 遍历 `app/ai/**`，import 只在 `app.ai.*` / `app.ports.ai_reads` / `app.config` / `app.db.session` + 标准库 + `httpx`/`sqlalchemy`；并断言 `app/adapters/domain/reads.py` 存在 |
| ports readonly | `tests/ai/test_ports_readonly.py` | `before_cursor_execute` 统计业务表 INSERT/UPDATE/DELETE（排除 `ops.audit_log`）为 0；`before_flush` 无非审计脏对象；记录型端口证明写/未许可/未识别请求端口调用为 0 |
| row-count | `tests/ai/test_risk_readonly.py` | 问风控前后 `risk.risk_policy` 行数不变；问市场前后 `market.market_session` 行数不变 |
| 语料单一事实源 | `backend/tests/ai/data/query_cases.json` | 测试与 `p4_smoke.sh` 步骤 6/7 读同一份语料，不再各维护一份清单 |

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 交易写符号 | `rg -n 'place_order\|cancel_order\|create_order' backend/app/ai` | 0 命中 |
| 反向依赖 | `rg -n 'from .*execution\|import .*execution' backend/app/{market,strategy,risk,backtest}` | 0 命中 |
| 业务表写 | `pytest -q tests/ai/test_ports_readonly.py` | 6 个端点业务写为 0（审计表除外） |
| api 层不直连 HTTP | `rg -n 'import httpx' backend/app/api` | 0 命中 |

决策性计算仍留在各域 `core` 的纯函数；`app/ai` 只调用各域服务读取既有结果、组织引用与文本，
不重算指标、不写业务表。唯一写入是 `ops.audit_log`，且只经 ORM。

## 6. 限制与工程债

1. **外部模型未做真实联调**：本环境没有可用的模型服务，验收使用 `rule_based` 与
   `MockTransport`。OpenAI 兼容适配器按 `/chat/completions` 契约实现，联网后应补一次真实端点验证。
2. **规则式回答不是生成式总结**：`rule_based` 直接输出确定性事实摘要，因此措辞固定；
   它的价值是可复现、可审计，不承担「自然语言润色」职责。
3. **写意图识别基于关键词**（下单/买入/卖出/改策略/改风控/审批/启动实盘等），偏保守：
   例如「解释买入逻辑」也会被判定为写意图而拒绝。只读助手宁可误拒，不可误执行。
4. **不持久化对话历史**：每次请求独立，`/ai/query` 不保存问答记录；如需多轮上下文，
   应另开迁移与脱敏方案，不在本次范围。
5. **`suggest` 只产草案**：不写入策略表、不提交审批；草案可能只有单边腿（当关系快照
   仅有一侧显著边时），响应 `warnings` 会显式提示。
6. **审计幂等键依赖 `X-Request-ID`**：调用方不传时服务端生成请求 id，重试会产生新审计行；
   需要严格幂等的调用方必须自带 `X-Request-ID`。
