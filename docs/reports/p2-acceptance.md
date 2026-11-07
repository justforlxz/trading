# P2 风控阶段验收报告（MKACG-700）

本阶段在 P1 策略与回测之上建立**策略级 + 全局组合两级风控**：不接触真实账户、不下单，
给出「能不能交易、能交易多少、超限怎么处置」的确定、可复现、可审计答案。全部判决 fail-closed：
K 线缺失、依赖不可用、计算异常一律拒绝放行，不抛 500。

## 1. 验证环境

| 项 | 实测值 |
| --- | --- |
| 日期 | 2026-11-07（UTC+8） |
| 代码 | 分支 `agent/agent/0116ed1637f2`，PR [#9](https://github.com/justforlxz/trading/pull/9)；本报告随被测提交一并提交，HEAD 即被测版本 |
| 基线 | `master@bb48233`（P1 交付） |
| 部署形态 | `docker compose -f infra/docker-compose.yml`，project `trading`，全部服务 `healthy` |
| 镜像 | `trading-api:local`（api/worker/scheduler 共用）、`trading-web:local`（nginx）、`postgres:16-alpine`、`redis:7-alpine` |
| 端口 | API `8000`、Web `5173` |
| 运行时 | Python 3.12（容器）、Node v22.23.2、pnpm 9.15.9、ruff（容器内 dev 镜像） |
| 迁移 | `alembic current` = `0007_risk_schema (head)` |
| 数据前提 | 冒烟脚本自建 P2 验收专用标的（`P2SMKA/P2SMKB-USDT-SWAP`）、2 腿组合、回测净值（100000 → 80000）；不依赖 P1 回补数据，可空库直接执行 |

## 2. 节点验收

| 节点 | 交付 | 验收证据 |
| --- | --- | --- |
| P2-01 风控数据模型与迁移 | `backend/app/risk/models.py`、`backend/alembic/versions/0007_risk_schema.py` | `alembic current` = `0007_risk_schema (head)`；`tests/risk/test_schema.py` 在全新测试库上 `alembic upgrade head` 后 head 仍为 0007，重复升级幂等，并断言两表、`uq_risk_policy_version`/`uq_risk_event_key`、`NUMERIC(24,10)`/`NUMERIC(12,10)` 精度 |
| P2-02 策略级限额校验 | `backend/app/risk/core/limits.py`、`tests/risk/test_limits.py` | 纯函数；单笔/单腿/杠杆/总敞口/净敞口/单标的/集中度七类限额；等于阈值放行、超 `1e-9` 容差拒绝 |
| P2-03 全局组合风险 | `core/portfolio.py`、`tests/risk/test_portfolio.py` | 总/净/多空敞口、集中度、多空冲突、跨策略重复持仓；与手算值误差 ≤ `1e-9` |
| P2-04 自动资金分配 | `core/allocation.py`、`tests/risk/test_allocation.py` | Σ分配 ≤ 总预算、单策略 ≤ 上限、高优先级不饿死；覆盖预算不足/低于最小下单额分支 |
| P2-05 最大回撤与分级处置 | `core/drawdown.py`、`tests/risk/test_drawdown.py` | 三级阈值各自可触发，`action ∈ {none,warn,reduce,close}`；同输入逐字段相同 |
| P2-06 资金费率与流动性 | `core/funding.py`、`app/adapters/okx/risk.py`、`GET /risk/funding`、`tests/risk/test_funding.py` | 录制 fixture 构造超资金费率与深度不足各产生一条 `risk_event`；缺失行情 fail-closed；单测不打真实网络 |
| P2-07 风控 API 与面板 | `app/api/v1/risk.py`、`app/risk/service.py`、`frontend/src/pages/risk/` | `tests/risk/test_api.py` 覆盖 6 个端点与错误信封；`pnpm --dir frontend build` 通过，`/risk` 页 200 且展示限额/事件/处置动作 |
| P2-08 阶段验收 | `scripts/e2e/p2_smoke.sh`、本报告 | `bash scripts/e2e/p2_smoke.sh` exit 0，覆盖「造组合 → 触发超限 → 分级处置 → 事件落库」 |

## 3. 门禁结果

| 命令 | 结果 |
| --- | --- |
| `make lint` | `ruff check .` / `ruff format --check .` 通过；`eslint` 0 error（3 条既有 warning） |
| `make test` | 通过（`tests/backtest/test_schema.py` 对旧 head 的硬编码断言已随迁移前移改为只断言结构完整 + 升级幂等，head 由 risk 侧断言） |
| `make coverage` | **375 passed，覆盖率 79.77%**（门槛 70%，未下调） |
| `pnpm --dir frontend lint && build` | 0 error；`tsc --noEmit && vite build` 成功 |
| `rg -n 'skip_risk\|disable_risk\|risk_bypass' backend/app` | 0 命中 |
| `rg -n 'place_order\|cancel_order\|/api/v5/trade' backend/app` | 0 命中 |
| `backend/app/execution`、`backend/app/ai` | 不存在（未预建空壳） |

## 4. 端到端验收链路（p2_smoke.sh 实测）

| 步骤 | 请求 | HTTP | 耗时 | 结论 |
| --- | --- | --- | --- | --- |
| 0 | `GET /health`、`GET /`（Web）、`alembic current` | 200 / 200 | 1458 ms | API `health=ok`，Web 200，迁移 `0007_risk_schema (head)` |
| 1 | `docker compose exec api python` 幂等写组合 | n/a | 1292 ms | `strategy_id=5`、`run_id=5`，2 腿（0.9 long / 0.5 short），净值 100000 → 80000 |
| 2 | `GET /risk/policy?strategy_id=5` | 200 | 184 ms | 自动创建阈值 `v1` |
| 3 | `PUT /risk/policy` | 200 | 114 ms | `v1 → v2`（单笔 10000、单腿 0.3、杠杆 0.5、总敞口 0.5、集中度 0.3、回撤 5/10/25%） |
| 4 | `GET /risk/status?strategy_id=5` | 200 | 37 ms | `allowed=false`、`reason=limit_breach`，命中 `order_notional/leg_weight/instrument_weight/concentration/gross_exposure/leverage` 共 6 类 |
| 5 | `POST /risk/evaluate` ×2 → `/ops/job-runs` 轮询 | 202 → 200 | 2187 ms | 任务 `ok`，10 条 `limit_breach` 事件；二次提交同 `run_id`、`created=false`，事件条数不增 |
| 6 | `GET /risk/events?kind=drawdown` | 200 | 28 ms | 回撤 20% → `action=reduce`、`severity=tier2` |
| 7 | `GET /risk/status`（全局） | 200 | 30 ms | `scope=global`、`allowed=false`、命中 3 条限额 |
| 8 | `PUT /risk/policy`（恢复） | 200 | 53 ms | `v2 → v3`，恢复默认阈值 |
| 9 | 汇总并写产物 | 200 | 13 ms | `docs/reports/p2-smoke-artifacts.json` |

补充实测：

- **缺字段阈值**：`PUT /risk/policy` 去掉 `max_leverage` → `422` + `{"code":"risk_invalid_threshold","details":{"missing":["max_leverage"]}}`，与 `api-contract.md §3.7` 一致。
- **风控面板**：浏览器打开 `/risk`，全局页显示 总敞口 240000 / 净 140000 / 杠杆 1.2 / 集中度 0.9 与 3 条命中，逐值与 `GET /risk/status` 一致；输入策略 5 点「重新评估」后显示该策略的限额与处置事件，数值全部来自 API。
- **不可绕过**：无任何 `skip_risk` 类开关；`strategy`/`backtest`/`market`/`analysis`/`opportunity` 均无 `from app.risk`。

## 5. 结论

- P2-01 ~ P2-08 全部节点完成，15 条 AC 均可由命令复现；风控功能本身、门禁、端到端链路、边界红线均通过。
- 门禁未放宽：覆盖率 79.77% ≥ 70%，lint 0 error，无下单类调用，`execution`/`ai` 未预建。
- 风控结论可复现可审计：阈值版本化、事件按评估键去重、同参数重复评估判决逐字段相同。
- 评测中提出的两项整改已闭环：缺字段阈值返回 `risk_invalid_threshold`（含 `details.missing`）；本报告补齐环境、逐步 HTTP/耗时、结论与工程债。

## 6. 设计与边界说明

- **分层**：`risk.core` 全是纯函数（输入 dataclass + `Decimal`，输出判决对象或确定错误码）；
  `risk.service` 只做查询、编排、事件落库；`api` 层不 import `httpx`，外部调用走 `adapters/okx/risk.py`。
- **单向依赖**：`risk` 只读引用 `strategy`/`market`/`backtest` 的数据，三者不 import `risk`；
  `risk` 不 import `execution`/`ai`。
- **阈值解析顺序**：传 `strategy_id` 时优先使用该策略的 `scope=strategy` 版本，缺省回落到全局版本。
- **幂等**：`risk_event` 唯一键 `(kind, strategy_id, instrument_id, policy_version, evaluation_key)`
  使用 `NULLS NOT DISTINCT`，同一评估键重复评估不新增事件行；`POST /risk/evaluate` 复用 `job_run` 幂等键。
- **金额与比例**：数据库列全为 `NUMERIC`，API 一律以字符串返回，计算全程 `Decimal`，无 float。

## 7. 已知限制与工程债

| # | 类型 | 内容 | 影响 |
| --- | --- | --- | --- |
| 1 | 工程债（P1 遗留） | `market.backfill` 未按批量参数分块，1h/4h 大区间回补受上游单次参数上限约束 | 大区间回补需手工分段，本阶段未修 |
| 2 | 工程债（P1 遗留） | `partial` 批次可能重复入队 | 重复采集开销，不影响风控正确性 |
| 3 | 设计取舍 | `GET /risk/status` 按契约不查 K 线，对无行情策略可能给 `allowed=true`，与 `POST /risk/evaluate` 的 `market_data_unavailable` 不同 | 面板已提供「重新评估」补足；后续可在契约注明或给 status 增加严格模式 |
| 4 | 契约待补 | `POST /risk/evaluate` 对不存在/未审批策略先返回 202、随后任务 `failed`，错误只在 `/ops/job-runs/{id}` 可见 | 契约未定义该场景，后续可改为入队前 404/409 预检 |
| 5 | 覆盖缺口 | `risk.service` 行覆盖率 65.2%（整体 79.77% 达标），缺口集中在全局面板与巡检编排分支 | 不阻塞本阶段，后续补 service 级用例 |
| 6 | 环境差异 | `GET /risk/funding` 依赖 OKX 公开行情，离网环境返回 `503 risk_market_data_unavailable`（fail-closed） | 单测使用录制 fixture，不依赖网络 |
| 7 | 验收工具 | `p2_smoke.sh` 步骤 1 通过 `docker compose exec` 直接写入验收专用组合（P2 尚无「创建组合」公开接口） | 其余断言全部走 HTTP API |
| 8 | 阶段边界 | 风控只给出「允许/拒绝 + 处置动作」判决与事件记录，不执行减仓/平仓（执行属 P3） | 符合本阶段范围 |
