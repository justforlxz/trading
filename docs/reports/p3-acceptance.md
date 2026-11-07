# P3 交易执行验收报告（MKACG-701 / S10）

**结论：P3 交付完成。本次运行 `REAL_TRADING_ENABLED=false`，全程未产生任何真实订单请求。**

## 1. 环境与前置

| 项 | 值 |
| --- | --- |
| 运行日期 | 2026-11-07（UTC） |
| 仓库基线 | `master@18795db`（MKACG-700 P2 风控合并后） |
| 数据库迁移 | `0008_execution_schema (head)`，`alembic current` 与 `alembic upgrade head` 幂等 |
| 运行形态 | Docker Compose 六服务（`postgres`/`redis`/`api`/`worker`/`scheduler`/`web`），全部 healthy |
| 真实交易开关 | `REAL_TRADING_ENABLED` **未设置**（缺省 `false`） |
| OKX 私有凭据 | 未配置（`okx_api_key`/`okx_api_secret`/`okx_api_passphrase` 均为空） |
| 执行模式 | `GET /api/v1/execution/mode` → `{"mode":"paper", "reason":"real_trading_disabled"}` |

paper 撮合按 `EXECUTION_PAPER_FILL_CHUNKS`（默认 `0.5,0.5`）分段成交，用于在无真实交易所的情况下
复现「部分成交 → 补成交」的状态迁移；这不是数据伪造，而是模拟器刻意的确定性行为。

## 2. 一键验收（`bash scripts/e2e/p3_smoke.sh`）

退出码 0。逐步耗时（同一台机器、同一 compose 栈）：

| 步骤 | 内容 | HTTP | 耗时(ms) | 结论 |
| --- | --- | --- | --- | --- |
| 0 | 预检：API 健康与 execution 迁移版本 | 200 | 1430 | 迁移 `0008_execution_schema (head)`；mode=paper |
| 1 | 造策略：幂等写入已审批策略与走平净值 + 重启 API 复位 paper 账本 | n/a | 8094 | `strategy_id=16`，2 腿 × 0.15 |
| 2 | 风控放行：`POST /risk/evaluate` | 202 | 2354 | `job_id=2477`，`allowed=true` |
| 3 | 模式端点 `GET /execution/mode` | 200 | 33 | mode=paper，reason=real_trading_disabled |
| 4 | paper 下单 `POST /execution/paper/orders` | 201 | 152 | `order_id=31`，state=partial，filled=0.5 |
| 5 | 补成交 `POST /execution/orders/31/sync` | 200 | 58 | state=filled，filled=1 |
| 6 | 下单后撤单 `POST /execution/orders/32/cancel` | 200 | 143 | state=canceled，已成交 0.2 |
| 7 | 持仓归因 `GET /execution/positions` | 200 | 77 | 持仓 1.2 = 订单成交量之和 |
| 8 | 对账 `POST /execution/reconcile` | 200 | 26 | checked_positions=1，open_diffs=0 |
| 9 | 真实重启 api 后 `POST /execution/recovery` | 200 | 7672 | rehydrated=3，reattached=1，order_c filled |
| 10 | 真实门禁：空请求体 `POST /execution/orders` | 403 | 29 | `real_trading_disabled` |

验收产物：`docs/reports/p3-smoke-artifacts.json`（含 `real_trading_enabled: false` 与逐步计数）。

脚本在同一套 compose 栈上连续执行两次均返回 0（第二次为可重复性回归）；步骤 1 结尾会重启 API，
清空进程内 paper 撮合账本并清空对账差异，因此重复执行不会因上一轮残留而失败。

步骤 9 是真正的进程重启：脚本执行 `docker compose restart api`，等待 `/health` 恢复后再调用恢复接口，
因此覆盖的是「进程内撮合状态丢失 + 数据库订单/成交留存」的真实场景，而不是同进程内的模拟。

## 3. 出口门禁

```bash
make lint && make test && make coverage
curl -s localhost:8000/api/v1/execution/mode | jq -e '.mode=="paper"'
env -u REAL_TRADING_ENABLED bash -c 'make up' && \
  curl -s -o /dev/null -w '%{http_code}' localhost:8000/api/v1/execution/orders -X POST
```

| 命令 | 结果 |
| --- | --- |
| `make lint` | 通过（ruff check / ruff format --check 全绿；前端 eslint 0 error） |
| `make test` | 通过：438 passed，前端 `vite build` 成功 |
| `make coverage` | 通过：438 passed，总覆盖率 **79.69%**（门槛 70%，未下调） |
| `GET /execution/mode` | `jq -e` 返回 `true`（mode=paper） |
| `env -u REAL_TRADING_ENABLED … POST /execution/orders` | 返回 **403**（`real_trading_disabled`） |

## 4. 逐条 AC 对照

| # | AC | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 迁移到 `0008_execution_schema` 且幂等，重建后表/约束存在 | ✅ | `tests/execution/test_schema.py`（版本、4 张表、唯一约束/CHECK、`NUMERIC(24,10)`、二次 `alembic upgrade head` 返回 0） |
| 2 | 签名与文档化签名原文逐字节一致；单测零真实网络 | ✅（附限制） | `tests/adapters/test_okx_private.py`：`build_prehash` 等于 `timestamp+METHOD+requestPath+body`，HMAC-SHA256+Base64 固定向量、`httpx.MockTransport` 全量拦截。**限制**：OKX 文档页为脚本渲染，本环境离线无法逐字抓取官方示例，故用固定向量回归签名原文，未与官方示例逐字对拍 |
| 3 | 状态机合法迁移通过，非法迁移抛确定错误且状态不变 | ✅ | `tests/execution/test_orders.py`：`pending→submitted→partial→filled`、终态迁移、`filled→partial` 抛 `execution_invalid_transition` |
| 4 | 同 `clOrdId` 重复提交返回同一订单且交易所调用次数不增加 | ✅ | `test_orders.py::test_duplicate_client_order_id_is_idempotent`（计数包装源：`place_calls == 1`） |
| 5 | 策略级持仓与盈亏之和 = 账户合计（≤1e-9），覆盖部分成交与多空同时持有 | ✅ | `tests/execution/test_positions.py`：分策略已实现盈亏之和与合并账本差 0；long/short 同时持有；`mark_to_market`/`account_totals` |
| 6 | 对账产出差异且不静默修数；未处理差异拒绝下单 | ✅ | `tests/execution/test_reconcile.py`：`position_mismatch` 记录后本地持仓仍为 1；`open_diffs=1` 时 `check_submit` 返回 `execution_reconcile_pending` |
| 7 | `GET /execution/mode` 为 paper；paper 下单 0 次真实调用 | ✅ | `tests/execution/test_paper.py`：模式端点断言；把 `OkxPrivateClient` 替换为「构造即失败」后 paper 下单仍成功 |
| 8 | 缺省关闭 403、开关开但未授权 403、未配凭据拒绝下单 | ✅ | `tests/execution/test_gate.py`（四道闸门单测 + HTTP 403 + 空请求体 403）；冒烟步骤 10 |
| 9 | 重启/断线后接管或安全撤销，不重复持仓、不丢单 | ✅ | `tests/execution/test_recovery.py`（paper 重启重建并补完、交易所查无此单 `pending→rejected`/其余 `→canceled`、重复恢复幂等）；冒烟步骤 9 真实重启 |
| 10 | 止损产生平仓单并写 `risk_event`，不经过策略审批 | ✅ | `tests/execution/test_stops.py`：`intent=stop`、`reduce_only`、`side=sell`、`risk_event(kind=stop_trigger)`、把 `risk_service.evaluate` 替换为抛错仍可触发 |
| 11 | `p3_smoke.sh` 退出 0，10 步覆盖全链路 | ✅ | 本报告 §2；共 10 个业务步骤 + 汇总 |
| 12 | 本报告记录「未产生真实订单」、环境、耗时、AC 对照、限制与工程债 | ✅ | 本文 |
| 13 | 出口门禁四条命令逐条通过 | ✅ | 本文 §3 |
| 14 | `make lint && make test && make coverage` 全绿，覆盖率 ≥70% | ✅ | 438 passed，79.69% |
| 15 | P1/P2 未破坏；下单相关符号命中范围受限；README 与文档同步 | ✅ | 438 passed（新增 63 条，既有用例全部继续通过）；`place_order|cancel_order|/api/v5/trade` 仅命中 `adapters/okx/private.py`、`api/v1/execution.py`、`execution/*`、`ports/private.py`；反向依赖 grep 0 命中；README 当前阶段与 `api-contract §3.9`、`data-model §9` 已同步 |

> 用例数：`make coverage` 报告 438 passed，其中新增 63 条（adapters 10 + execution 53）；
> 其余既有用例全部继续通过（issue 描述的 P1/P2 基线为 374，本次全量运行比基线多 1 条，差额来自 MKACG-700 合并后的既有用例）。

## 5. 分层与红线自检

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 反向依赖 | `rg -n 'import.*execution' backend/app/strategy backend/app/risk backend/app/market` | 0 命中 |
| 下单符号边界 | `rg -n 'place_order\|cancel_order\|/api/v5/trade' backend/app` | 仅 `adapters/okx/private.py`、`api/v1/execution.py`、`execution/paper.py`、`execution/service.py`、`ports/private.py` |
| 硬编码凭据 | `rg -n 'api_key\s*=\s*"[A-Za-z0-9]' backend` | 0 命中 |
| api 层不直连 HTTP | `rg -n 'import httpx' backend/app/api` | 0 命中 |

决策性计算（状态机、持仓数学、门禁判定）全部在 `app/execution/core/*` 与 `execution/gate.py` 的纯函数里，
编排层只做查询与落库；交易所原始 JSON 只出现在 `app/adapters/okx/private.py`。

## 6. 限制与工程债

1. **实盘链路未做真实资金验证**。按任务约束，本次验收不允许打开 `REAL_TRADING_ENABLED`，也未配置真实凭据；
   OKX 私有接口只用 `MockTransport` 覆盖签名、参数与错误码，未与生产端点联调。
2. **官方签名测试向量未逐字抓取**（见 AC2 限制）。实现按 OKX v5 文档的签名原文规则编写，
   单测用固定 `(secret, timestamp, path, body)` 组合做回归；下一次能联网时应补一条与官方示例逐字对拍。
3. **paper 撮合是确定性模拟器**：成交价取最近确认 K 线收盘价，手续费为 0，分段比例来自配置，
   不代表真实滑点/深度/资金费率。它的作用是驱动订单生命周期与持仓归因，不是收益预测。
4. **止损写 `risk_event` 的方式**：执行域通过 `app.risk.service.record_event` 这个公开入口写入，
   不直接 SQL 写 `risk` 表；这是「执行域只读 strategy/risk/market」红线之外唯一一处受控跨域写，
   已在 `docs/architecture/api-contract.md §3.9` 记录。
5. **`execution."order"` 使用 PostgreSQL 保留字作表名**（与 data-model §9 的命名一致），
   原生 SQL 必须加引号；ORM 与 Alembic 已自动加引号，测试中也按引号写法覆盖。
6. **未做前端页面**：P3 无前端交付物，执行域只有 REST 契约。
7. **超量平仓在落库前拒绝**：`reduce_only` 数量超过该策略持仓时返回
   `409 execution_position_inconsistent`（details 带 `requested`/`available`），不创建订单、不触达
   交易所/模拟撮合器；成交落账失败时订单立即收敛到 `rejected`/`canceled` 终态，不会留下僵尸单。
   模拟撮合器对 `reduce_only` 只按现有持仓截断，`fetch_positions` 对历史脏成交跳过而非抛错，
   因此对账与重启恢复不会因一次误操作永久 500。冒烟脚本在步骤 1 后会重启 API 清空进程内撮合账本，
   保证同一套栈可重复执行。
8. **下单幂等依赖调用方传 `client_order_id`**：未传时服务端生成随机 id，网络重试会产生新订单；
   需要严格幂等的调用方必须自带 `clOrdId`。同 key 但载荷不同返回 `409 execution_idempotency_conflict`；
   并发同 key 由唯一约束兜底并收敛为返回既有单（不会双下单）。
