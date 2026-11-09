# 1.0 发布说明（MKACG-703 / S12-06）

**1.0 可交付。** P1–P4 四个阶段的能力全部落地并可用一条命令复验；门禁全绿（`make lint` 0 错、
`make test` 548 passed、`make coverage` **78.69%** ≥ 70%）；干净库上一键验收脚本步骤 0–9 全通过（97 秒）；
四类故障注入脚本 exit 0 且恢复后无脏写；安全红线全部满足（`mode=paper`、实盘开关默认关闭、未授权实盘下单 403、
`mode='real'` 订单 0 条）。**本轮没有下过任何真实订单，没有动用任何真实资金。**

唯一的交付缺口是 **Kubernetes 部署形态未交付**，已作为工程债登记（§5.1），不计入 1.0 能力。

## 1. 发布信息

| 项 | 值 |
| --- | --- |
| 版本 | `v1.0.0`（合并后在合并提交上打 tag；仓库当前无 tag） |
| 代码基线 | `master@7dfe8cd`（S11 合并）+ 本 issue 的 S12 集成验收改动 |
| 数据库迁移 | `0009_mcp_schema`（`0001`→`0009` 单向线性链，`alembic current` 必须为 `(head)`） |
| 部署形态 | Docker Compose 六服务：`postgres`、`redis`、`api`、`worker`、`scheduler`、`web`（另有 `api-dev` 仅用于门禁） |
| 对外接口 | REST `/api/v1/**`（market / targets / opportunities / strategies / backtests / risk / execution / mcp-clients）+ MCP `POST /mcp`（JSON-RPC 2.0 / SSE）+ `/health`、`/ready` |
| 前端 | React 18 + Vite，6 个页面（11 个视图文件）：仪表盘、研究、策略、回测详情、风控、设置 |
| MCP 工具 | 18 个只读工具 + 8 个受控操作工具（无裸下单、无审批、无实盘授权） |
| 实盘状态 | `REAL_TRADING_ENABLED=false`、无 OKX 凭据、`mode=paper`（交付时默认且全程如此） |
| 运行手册 | `docs/runbook.md`（部署 / 配置 / 备份恢复 / 升级回滚 / 故障排查 / 日志位置） |

## 2. 能力清单（P1–P4）

每行都给出实现位置、验证命令与实际结论；**没有空行，没有「待补」**。

### P1 交易前准备

| 能力 | 实现位置 | 验证命令 | 结论 |
| --- | --- | --- | --- |
| 标的同步（OKX 美股永续全量） | `backend/app/api/v1/market.py`、`market/instruments.py`、`adapters/okx/` | `full_smoke.sh` 步骤 1；`pytest -q tests/market` | ✅ 543 个标的入库（其中美股永续 230），按小时窗口幂等 |
| 行情采集与保留策略 | `market/candles.py`、`market/retention.py`、`jobs/`、`docs/market-data.md` | `full_smoke.sh` 步骤 1（回补 230 个任务、GOOGL 251 根日线） | ✅ 1m/5m/15m 保 90 天、1h/4h/1d 全量；`market.candle` 无重复行（`count(*) - count(distinct (instrument_id,bar,open_time)) = 0`） |
| 行情来源与市场时段标记 | `market/sessions.py`、`market/sync_status.py`、`research/market_snapshot` | `pytest -q tests/market/test_sessions.py`（6 passed） | ✅ 区分美股交易时段与休市，标注来源与时间戳 |
| 目标股票管理 | `research/targets.py`、`api/v1/research.py` | `full_smoke.sh` 步骤 2；`p1_smoke.sh` | ✅ 首次创建 201、重复创建 200（`(symbol, exchange)` 唯一键幂等） |
| 动态相关性（关系快照与边） | `research/relations.py`、`analysis/` 纯函数 | `full_smoke.sh` 步骤 2（174 条边）、`pytest -q tests/research` | ✅ 支持 pearson/spearman、best_lag、p 值、稳定性与排名 |
| 相对强弱 | `research/relative_strength.py`、`GET /targets/{id}/relative-strength` | `full_smoke.sh` 步骤 2（RDDT rs_ratio=1.3904） | ✅ 输出 rs_ratio / rs_momentum / excess_return 与序列 |
| 市场共振与聚类 | `opportunity/scanner.py`（广度、聚类） | `full_smoke.sh` 步骤 3（9 个簇，187 涨 / 43 跌） | ✅ |
| 机会发现（方向性 + 相对价值） | `opportunity/scanner.py`、`opportunity/query.py`、`POST /opportunities/scan` | `full_smoke.sh` 步骤 3（run_id=1，49 条机会：9 方向性 / 40 相对价值） | ✅ 每条机会带 `reasons[]` 与 `evidence{}` |
| 策略生成（模板组合） | `strategy/core/templates.py`、`builder.py`、`constraints.py` | `full_smoke.sh` 步骤 4（6 条腿，Σ\|w\|=1） | ✅ 必须带来源（`strategy_source_required`），腿必须有证据 |
| 策略审批状态机 | `strategy/state_machine.py`、`strategy/api.py` | `full_smoke.sh` 步骤 4（draft→pending_approval→approved） | ✅ 非法迁移 409 `strategy_illegal_transition`；状态迁移全量审计 |
| 历史回测与指标 | `backtest/service.py`、`POST /backtests` | `full_smoke.sh` 步骤 5（10 个指标 / 121 个净值点 / 6 笔成交） | ✅ 未审批策略 409、数据不足 422；同参数复用 run（200 `created=false`） |
| 前端研究工作台 | `frontend/src/pages/research/*`、`pages/dashboard.tsx`、`pages/strategies/`、`pages/backtests/` | `p1_smoke.sh` 步骤 10（SPA 路由 200） | ✅ 关系网络图、相关性表、K 线、仪表盘、策略与回测页 |

### P2 风控管理

| 能力 | 实现位置 | 验证命令 | 结论 |
| --- | --- | --- | --- |
| 策略级 + 全局两级风控策略（版本化） | `risk/service.py`、`risk/core/`、`GET/PUT /risk/policy` | `full_smoke.sh` 步骤 6（v1→v2→v3）；`p2_smoke.sh` | ✅ 阈值版本化，过期版本写入 409 `risk_policy_stale` |
| 限额评估与违规事件 | `risk/core/limits.py`、`POST /risk/evaluate` | `full_smoke.sh` 步骤 6（gross_exposure / leverage / net_exposure / order_notional 四类命中，6 条 `limit_breach`） | ✅ 同 `evaluation_key` 重放 `created=false`，事件不重复 |
| 回撤分级处置 | `risk/core/drawdown.py` | `p2_smoke.sh` 步骤 4–6（warn → reduce → tier2） | ✅ 回撤命中时对外 `reason=drawdown`（处置优先级高于限额） |
| 资金费率与流动性监控 | `risk/core/funding.py`、`GET /risk/funding`、`risk/data.py` | `pytest -q tests/risk`；`p3_smoke.sh` | ✅ 上游不可用时 fail-closed（503），不假装通过 |
| 全局组合敞口与多空冲突 | `risk/core/portfolio.py`、`risk/core/allocation.py` | `p2_smoke.sh`（全局 status 3 项 breach，allowed=false） | ✅ 净敞口、集中度、单标的权重均纳入判定 |

### P3 交易执行

| 能力 | 实现位置 | 验证命令 | 结论 |
| --- | --- | --- | --- |
| 实盘门禁（三重前提 + 请求体前置） | `execution/service.py`、`GET /execution/mode` | `security_audit.sh` B1–B5；`p3_smoke.sh` 步骤 10 | ✅ 空请求体也 403 `real_trading_disabled`；`mode='real'` 订单 0 |
| paper 撮合（两段部分成交） | `execution/paper.py`、`POST /execution/paper/orders` | `full_smoke.sh` 步骤 7（order_id=1 部分成交 → sync → filled）；`p3_smoke.sh` 步骤 4–5 | ✅ 默认分片 `0.5,0.5`，`partial`→`filled` |
| 订单生命周期 | `execution/service.py`、`POST /execution/orders/{id}/(cancel\|sync)` | `p3_smoke.sh` 步骤 6（撤单）、步骤 5（同步） | ✅ 非法状态迁移被拒；成交与手续费落 `execution.fill` |
| 策略级虚拟持仓与收益归因 | `execution/service.py`（positions 查询）、`execution/reconcile.py`、`GET /execution/positions` | `p3_smoke.sh` 步骤 7（持仓 1.2 与成交量之和一致） | ✅ 持仓可由成交反推，归因到策略 |
| 账户对账 | `POST /execution/reconcile`、`GET /execution/reconcile/diffs` | `p3_smoke.sh` 步骤 8（`open_diffs=0`） | ✅ 差异持久化并可按状态查询 |
| 故障恢复 | `POST /execution/recovery`、`execution/recovery.py` | `p3_smoke.sh` 步骤 9（重启后 reattached=1 / rehydrated=3） | ✅ 重启后恢复与实盘状态一致 |
| 自动止损 | `execution/stops.py`、`POST /execution/stops/evaluate`、`EXECUTION_STOP_LOSS_RATIO` | `pytest -q tests/execution` | ✅ 触发后按风控处置链路减仓/平仓 |
| 前端风控与设置页 | `frontend/src/pages/risk/index.tsx`、`pages/settings.tsx` | `p1_smoke.sh`（前端 200）；`pnpm --dir frontend build` | ✅ 风控状态、事件、MCP 客户端管理可在界面操作 |

### P4 MCP 服务（ADR-0007：用 MCP 取代内置 AI）

| 能力 | 实现位置 | 验证命令 | 结论 |
| --- | --- | --- | --- |
| MCP 协议（JSON-RPC 2.0 / SSE / 批量 / 通知） | `backend/app/mcp/{server,protocol,api}.py`、`POST /mcp` | `full_smoke.sh` 步骤 8；`pytest -q tests/mcp`（13 个测试文件） | ✅ `initialize`/`ping`/`tools/*`/`resources/*` 全通 |
| 令牌鉴权（sha256 存储、即时吊销） | `mcp/auth.py`、`mcp/models.py`、`/api/v1/mcp/clients` | `security_audit.sh` A1–A6 | ✅ 无/错/吊销令牌 401；令牌只返回一次；仅存哈希 |
| 作用域（read / operate）与越权拒绝 | `mcp/auth.py`、`mcp/tools.py` | `security_audit.sh` A4；`tests/mcp/test_auth.py`（14 passed） | ✅ 只读令牌调操作工具 403 `mcp_forbidden`，业务表零变化 |
| 18 个只读工具 | `mcp/tools.py`（`market_status` … `virtual_positions`） | `full_smoke.sh` 步骤 8（`get_strategy` 与 REST 一致） | ✅ 结果与 REST GET 等价（同一 service 层） |
| 8 个受控操作工具 | `mcp/tools.py`（`trigger_scan` … `execute_strategy_action`） | `pytest -q tests/mcp`；`docs/mcp.md` | ✅ 全部走既有业务入口，不绕过风控与审批 |
| 调用审计 | `mcp/audit.py`、`mcp.mcp_call_log` | `security_audit.sh` A4（被拒也留审计）+ `tests/mcp/test_audit.py` | ✅ 工具名、状态、错误码、耗时、参数摘要 |
| stdio 包装器 | `backend/app/mcp/stdio.py`（入口 `trading-mcp`） | `pytest -q tests/mcp/test_stdio.py` | ✅ 只转发 JSON-RPC，不缓存不改写 |
| 前端 MCP 设置 | `frontend/src/pages/settings.tsx`、`lib/api.ts` | `pnpm --dir frontend build`；`security_audit.sh` | ✅ 创建/查看/吊销客户端（令牌只显示一次） |

## 3. 门禁与验收（本轮实测）

| 门禁 | 命令 | 实测 | 结论 |
| --- | --- | --- | --- |
| 静态检查 | `make lint` | 退出 0；后端 `ruff check` 通过、235 个文件已格式化；前端 0 error（3 个 `react-refresh` warning） | ✅ |
| 测试 | `make test` | 退出 0；**548 passed**（76 s），前端 `pnpm build` 成功 | ✅ |
| 覆盖率 | `make coverage` | 退出 0；**548 passed, TOTAL 9034 行语句 / 1925 未覆盖 = 78.69%**，阈值 70% | ✅ |
| 全链路验收（AC1/AC10） | `down -v && make up` → `bash scripts/e2e/full_smoke.sh` | 步骤 0–9 全通过，**97 s**；6 容器 healthy；迁移 `0009_mcp_schema (head)`；543 标的 / 230 回补任务 / 174 关系边 / 49 机会 / 6 腿策略 / 10 指标 / 6 风控事件 / paper 订单 1 / MCP 越权 403 | ✅ |
| 幂等重跑（AC2） | 连续跑第二次 `full_smoke.sh` | 业务表行数不变（`market.instrument` 543、`strategy.strategy` 1、`backtest_run` 1、`execution.order` 1、`risk_event` 6 …）；按设计增长：`market.candle` +10（上游新确认 bar）、`mcp.mcp_clients` +1（轮换）、`risk.risk_policy` +2（两次版本化放宽）、`ops.job_run` +2（周期任务） | ✅ |
| 故障注入（AC3） | `bash scripts/e2e/chaos.sh` | 退出 0；四类故障（Redis 停机 / PG 停机 / 上游 429 / worker 重启）均实测；恢复后 candles 与订单数不变、重复 K 线 0 行 | ✅ 详见 `chaos-report.md` |
| 性能基线（AC4） | `docs/reports/perf-baseline.md` | 全池回补 230 标的 **71.1 s**（3.23 任务/s）、全市场扫描 **3.24 s**（230 标的 / 203 可分析）、关键 GET p95 ≤ 13 ms、MCP 只读 p95 50 ms | ✅ |
| 安全审计（AC5） | `bash scripts/e2e/security_audit.sh` | 退出 0，且**逐项断言全部通过**（不再只是「跑完即通过」）；密钥扫描 0 命中；MCP 401/401/403/401 四种失败态符合；越权调用业务表零变化且只留 1 条 `denied` 审计；未授权实盘下单 403；`mode='real'` 订单 0。姿态门禁负向验证：桩服务伪装 `real_trading_enabled=true` 时脚本退出 1，且未发出任何 `POST /execution/orders` | ✅ 详见 `security-audit.md` §1.1 |
| 文档一致性（AC6） | 见 `security-audit.md` §5 | 三处不一致全部**已修**（api-contract 增 §3.10 MCP；data-model 增 mcp schema 与 `strategy.paused_at`；p2-p4 §3 旧 AI 表标注作废） | ✅ |
| 运行手册（AC7） | `docs/runbook.md` | 六节齐全；**空目录部署实测**：`cp .env.example .env && make up` 78 s → 6 容器 healthy、`/health` 200、`/ready` 200、前端 200、迁移 head；备份 1.4 MB 可恢复；空库迁移 17.7 s、`downgrade -1` 可逆 | ✅ |
| 阶段回归（AC12） | `p1_smoke.sh` → `p2_smoke.sh` → `p3_smoke.sh`（干净库，按序） | 三个脚本全部退出 0 | ✅ |
| 密钥扫描（AC13） | `rg -n 'api_key\s*=\s*"[A-Za-z0-9]\|secret\s*=\s*"[A-Za-z0-9]' backend scripts` | 0 命中（退出码 1） | ✅ |
| 范围自证（AC14） | `git diff --name-only` | 只涉及 `scripts/`、`docs/`、`infra/docker-compose.yml`+`infra/.env.example`（新增故障注入接缝）、`README.md`；`backend/app` 零改动 | ✅ 见 §6 |

**覆盖率口径说明**：S10 基线是 438 passed / 79.69%，本次是 548 passed / 78.69%——测试数增加 110 个
（MCP 交付带来 `tests/mcp/` 13 个测试文件），分母多了 MCP 相关代码；依然高于 70% 阈值。覆盖率最低的模块是
`strategy/sources.py`（29.5%），它的分支几乎都由端到端脚本（`full_smoke.sh` 步骤 4、`p2_smoke.sh`）
而非单测覆盖，属于「集成覆盖、单测偏薄」，已列入 §5 工程债。

## 4. 已知限制（能力边界，不是缺陷）

1. **只交易 paper**：1.0 不启用真实资金；实盘需要用户显式开启 `REAL_TRADING_ENABLED=true`、填 OKX 凭据、
   并把策略 id 加进 `EXECUTION_REAL_STRATEGY_IDS`（三重前提），且需逐策略书面授权。
2. **无内置 LLM**：P4 按 ADR-0007 以 MCP 对外暴露能力，不做自然语言理解、不生成结论文字；分析能力交给外部 Agent。
3. **单实例单 worker**：worker 并发度为 1；扩容顺序是「先加 worker 并发，再考虑分片」（`perf-baseline.md` §6）。
4. **行情池按需回补**：默认只对配置里的少数标的（AAPL/SPY/QQQ/NVDA/TSLA）做行情对齐与日线入库；
   全市场扫描覆盖 230 个美股永续，但历史深度受上游限制（部分标的 `insufficient_bars`）。
5. **paper 撮合是固定两段 0.5/0.5**：不是真实撮合模型，只用于验证订单生命周期。
6. **美股行情源依赖第三方**：Yahoo 侧出现过 429，降级到 OKX 收盘价口径（`price_basis=okx_close`）。
7. **无 TLS / 无网关**：Compose 直接暴露 8000/5173，生产化需在前面加反向代理。

## 5. 工程债（登记，不构成 1.0 承诺）

### 5.1 Kubernetes 部署形态未交付

S12 计划的「生产环境可选 K8s」**没有实现**：仓库里没有任何 K8s manifest/Helm chart。
本 issue 的交付物清单里也没有它，因此不计入能力表，只作为债登记。
迁移路径：以现有 `infra/docker-compose.yml` 为唯一真相，产出 Deployment/Service/StatefulSet（PG 用
外部托管或 Operator）、ConfigMap/Secret 承接 `.env` 的变量清单，探针直接复用 `/health`（liveness）与
`/ready`（readiness），迁移用一次性 Job 跑 `alembic upgrade head`。此前的验收脚本（`full_smoke.sh`）
只依赖 `localhost:8000`，改 kube port-forward 即可复用。

### 5.2 其它工程债

| 编号 | 问题 | 证据 | 建议 |
| --- | --- | --- | --- |
| D1 | 派发失败留下永远 `queued` 的 `ops.job_run` 行，占住幂等键 → 同参数重放返回 200 `skipped` 但数据不进 | `chaos-report.md` §2.1、§6.1 | 派发抛错时把 run 标 `failed`；worker 启动时回收超时 `running` 行（涉及 6 处派发调用点，超出 S12 集成范围） |
| D2 | 基础设施故障响应不统一：Redis 停机时 `POST /market/backfill` 返回 500 纯文本、PG 停机时读接口 500 纯文本（`/ready` 是正确的 503 信封） | `chaos-report.md` §2.2、§6.2 | 在全局异常处理器里把 `OperationalError`/队列错误映射成 503 + 错误信封 |
| D3 | worker 被 SIGKILL 后，在途任务的行永远 `running`（arq 不恢复） | `chaos-report.md` §2.4、§6.3 | 启动时把 `running` 且 `worker` 不存在的行标 `failed`，让下一次重放能重跑 |
| D4 | 容器日志无轮转上限（默认 `json-file`，未配 `log-opts`） | `docs/runbook.md` §6 | 宿主机 `daemon.json` 配 `max-size`/`max-file`，或接集中式采集 |
| D5 | MCP 无速率限制；令牌无自动过期，轮换靠「吊销 + 新建」 | `security-audit.md` §6 | 网关层限流 + 令牌加 `expires_at` |
| D6 | `strategy/sources.py` 单测覆盖率 29.5% | `make coverage` 输出 | 补来源校验与证据装配的定向单测 |
| D7 | 前端 3 个 `react-refresh/only-export-components` warning | `make lint` 输出 | 把常量/工具函数拆出组件文件 |
| D8 | `docs/plan/p2-p4.md` §3 的历史 AI 计划表保留原文（已显式标注作废） | `security-audit.md` D3 | 保留追溯即可，不再作为待办 |

## 6. 本轮改动范围（范围自证）

`git diff --name-only` 相对 `7dfe8cd`：

```text
README.md                                   # 1.0 状态、文档索引、验收脚本入口
docs/architecture/api-contract.md            # + §3.10 MCP
docs/architecture/data-model.md              # + mcp schema、strategy.paused_at、迁移链表
docs/plan/p2-p4.md                           # 旧 AI 表显式作废
docs/runbook.md                              # 新增运维手册
docs/reports/release-1.0.md                  # 本文
docs/reports/security-audit.md               # 新增安全审计
docs/reports/chaos-report.md                 # 新增故障注入报告
docs/reports/perf-baseline.md                # 新增性能基线
docs/reports/*-artifacts.json                # 验收脚本产物（full-smoke / chaos / p1 / p2 / p3）
infra/docker-compose.yml                     # + OKX_REST_BASE_URL（故障注入接缝，默认值不变）
infra/.env.example                           # + OKX_REST_BASE_URL 说明
scripts/e2e/full_smoke.sh                    # 新增：全链路一键验收
scripts/e2e/chaos.sh                         # 新增：四类故障注入
scripts/e2e/security_audit.sh                # 新增：安全审计探针
scripts/e2e/p1_smoke.sh / p2_smoke.sh / p3_smoke.sh  # 迁移版本断言改为「处于 head」；p2 接受 drawdown 作为对外原因
```

**`backend/app` 与 `frontend/src` 零改动**——1.0 是集成验收与发布，没有新增业务能力。

## 7. 复现清单

```bash
# 门禁
make lint && make test && make coverage

# 干净库 + 全链路验收（AC1/AC10）
docker compose -f infra/docker-compose.yml down -v && make up
bash scripts/e2e/full_smoke.sh

# 阶段回归（按 p1 → p2 → p3 顺序，各脚本假设自己对数据库有独占写权）
bash scripts/e2e/p1_smoke.sh
bash scripts/e2e/p2_smoke.sh
bash scripts/e2e/p3_smoke.sh

# 故障注入与安全审计
bash scripts/e2e/chaos.sh
bash scripts/e2e/security_audit.sh
```

`full_smoke.sh` / `chaos.sh` 的产物默认写 `$HOME/.cache/s12/`，不弄脏工作区；要刷新仓库内
`docs/reports/*-artifacts.json` 时显式传 `ARTIFACT=docs/reports/<名字>.json`。
`security_audit.sh` 是逐项断言 + 姿态门禁：只有全部断言通过才退出 0，在非 `paper` +
`REAL_TRADING_ENABLED=false` 的部署上会在发出任何下单请求之前中止。

## 8. 验收证据索引

| 证据 | 位置 |
| --- | --- |
| 全链路验收原始数据 | `docs/reports/full-smoke-artifacts.json` |
| 故障注入原始数据与报告 | `docs/reports/chaos-artifacts.json`、`docs/reports/chaos-report.md` |
| 性能基线 | `docs/reports/perf-baseline.md` |
| 安全审计 | `docs/reports/security-audit.md` |
| 阶段验收 | `docs/reports/p1-acceptance.md`、`p2-acceptance.md`、`p3-acceptance.md` 及其 `*-smoke-artifacts.json` |
| 运维 | `docs/runbook.md` |

## 9. 发布判定

- 功能：P1–P4 能力齐备，全链路一条命令可复验 → **通过**
- 门禁：lint / test / coverage 全绿（78.69% ≥ 70%）→ **通过**
- 安全：三条红线（paper 默认、实盘默认关、未授权下单 403）实测成立，无真实资金动作 → **通过**
- 运维：空目录部署、备份恢复、升级回滚、故障排查、日志位置齐备且实测可执行 → **通过**
- 缺口：K8s 形态未交付（§5.1，已登记）→ **不影响 1.0，但必须在下一版本前清偿或正式取消**

**结论：可交付。** 合并后在合并提交上打 `v1.0.0`。
