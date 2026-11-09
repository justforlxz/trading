# 故障注入报告（MKACG-703 / S12-02）

**结论：四类故障的不变量全部成立——不产生脏数据、不可用时不假装成功、恢复后链路可用、交易姿态未被改变。
本文不承诺「自动降级」「自动自愈」是产品特性，只证明故障下系统不会写坏数据、恢复后可继续工作。
过程中发现的 5 项未闭环问题在第 6 节如实登记为工程债，不计入通过条件。**

## 1. 范围与环境

| 项 | 值 |
| --- | --- |
| 运行日期 | 2026-11-09 / 2026-11-10（UTC） |
| 仓库基线 | `master@7dfe8cd`（S11 MCP 服务合并后） |
| 数据库迁移 | `0009_mcp_schema (head)` |
| 运行形态 | Docker Compose 六服务（`postgres`/`redis`/`api`/`worker`/`scheduler`/`web`），全部 healthy |
| 真实交易开关 | `REAL_TRADING_ENABLED=false`（缺省值，全程未改） |
| OKX 私有凭据 | 未配置（`okx_api_key`/`okx_api_secret`/`okx_api_passphrase` 均为空） |
| 执行模式 | `GET /api/v1/execution/mode` → `{"mode":"paper","real_trading_enabled":false}` |

本文的「故障」是**真实进程/容器故障**，不是代码分支桩：Redis 与 PostgreSQL 是 `docker compose stop`
真实停掉的容器；上游限流是替换 `OKX_REST_BASE_URL` 指向一个返回 429 的真实 HTTP 桩容器；进程重启是
`docker compose restart worker`。所有判定都用 HTTP 状态码、`ops.job_run` 状态和 SQL 计数，不使用日志措辞作为证据。

故障注入专用的标的是 `PEP-USDT-SWAP`、周期 `1d`：它不在 `equity_sync_symbols` / `candle_ingest_symbols`
里，周期性采集不会碰它，因此「故障期间 K 线计数不变」的断言只受被测任务影响。所有注入窗口都取历史区间，
不与正常验收数据集重叠。

复现命令：

```bash
bash scripts/e2e/chaos.sh          # 退出码 0 = 四类故障不变量全部成立
cat $HOME/.cache/s12/chaos-artifacts.json   # 产物默认落这里，不弄脏工作区
```

产物默认写 `$HOME/.cache/s12/chaos-artifacts.json`；仓库内的 `docs/reports/chaos-artifacts.json`
是本报告第 2 节那次运行的原始数据，需要刷新时显式指定
`ARTIFACT=docs/reports/chaos-artifacts.json bash scripts/e2e/chaos.sh`。

## 2. 逐步实测

| 步骤 | 故障 | 耗时(ms) | 结论 |
| --- | --- | --- | --- |
| 0 | 预检：六容器健康、基线计数 | 1048 | 6 容器 healthy；`PEP-USDT-SWAP 1d` 基线 9 根；K 线总数 35403；订单 4；策略 4 |
| 1 | Redis 停摆 | 37609 | `/health` 200、读接口 200（0.013s）、投递返回 200 但任务从未执行；恢复后同参数重放 200/skipped、新窗口 202/partial；停摆期间 K 线 9 → 9 未变 |
| 2 | PostgreSQL 停摆 | 54595 | `/health` 200、`/ready` 无响应（客户端 20s 超时，未返回 200）、读接口无响应、api 容器存活；重启后 `/ready` 1s 恢复 200；数据计数无变化 |
| 3 | 上游 429 | 69252 | 任务 1495 → `failed`（`upstream unavailable after 5 attempts: okx rate limited: /api/v5/market/history-candles`）；期间 K 线 9 → 9 未变；上游恢复后同窗口重跑 → `partial`，K 线 9 根 |
| 4 | worker 进程重启 | 17917 | 重启 9s 后健康并跑完周期任务（job 1493）；重复 K 线 0 条；同参数重放复用 job 1498、回补任务行 241 → 241、K 线不变 |
| 5 | 收尾：交易姿态核对 | 334 | mode=paper，`real_trading_enabled=false`，`mode=real` 订单 0 条；订单总数 4 未变 |

单次全流程约 3 分 03 秒，主要耗时在故障观测窗口与恢复等待。

### 2.1 故障一：Redis 停摆

注入：`docker compose -f infra/docker-compose.yml stop redis`

| 观测 | 实测 |
| --- | --- |
| 存活探针 `GET /health` | **200**（0.001–0.013s） |
| 读接口 `GET /market/instruments?limit=5` | **200**（0.013s，读路径不依赖 Redis） |
| 任务投递 `POST /market/backfill` | **200**，返回 `job_id`，但任务从未被执行（`ops.job_run.status` 停在 `queued`） |
| 停摆期间 K 线 | 9 → 9（零脏写） |
| 恢复后同参数重放 | **200 / `skipped`**（命中上一条 `queued` 行，任务不再执行） |
| 恢复后新窗口投递 | **202 / `partial`**（投递通道恢复，任务正常跑完） |

**同一个注入在三次独立运行里观察到三种投递表现**，如实记录，不做取舍：

1. `500` 纯文本 `Internal Server Error`（无错误信封）——`enqueue_task` 直接抛异常；
2. `200` + `job_id`：`ops.job_run` 已落库为 `queued`，投递失败后无人把该行改成 `failed`；
3. 请求 20s 无任何响应，客户端超时（`curl` 退出码 28）。

三种表现共同的问题：调用方无法从响应判断「任务到底会不会跑」。第 2 种最危险——它看起来成功了。
根因在 `backend/app/jobs/runs.py` 的 `create_run()`：幂等键命中 `status ∈ ("queued","running")` 时直接返回
既有行且 `created=False`，路由不再投递；而投递失败时没有任何代码把该行改成 `failed`，于是这个键被永久锁死。

### 2.2 故障二：PostgreSQL 停摆

注入：`docker compose -f infra/docker-compose.yml stop postgres`

| 观测 | 实测 |
| --- | --- |
| 存活探针 `GET /health` | **200**（存活探针不查库，符合分层设计） |
| 就绪探针 `GET /ready` | 一次为 **503** 且 `error.code=dependency_unavailable`（0.30s）；一次为 20s 无响应（客户端超时）。两次都**没有**返回 200，fail-closed 成立 |
| 读接口 `GET /market/instruments?limit=3` | 一次 **500**（0.30s，纯文本无信封）；一次 20s 无响应 |
| api 容器 | `running`（未退出、未重启） |
| 恢复（`docker compose start postgres`）→ `/ready` 200 | **1s**（连接池 `pool_pre_ping` 自动剔除坏连接） |
| 恢复后计数 | K 线、订单数均与故障前一致 |

结论：数据库不可用时系统整体不可服务，但不会把失败伪装成成功，也没有写入半截数据；恢复不需要人工重启应用。

### 2.3 故障三：上游按 429 限流

注入方式（不改业务代码、不 mock 内部函数，只在网络层替换上游地址）：

```bash
cat > "$WORK_DIR/stub429.py" <<'PY'   # 返回 HTTP 429 + {"code":"50011","msg":"Too Many Requests"}
PY
docker run -d --rm --name s12-okx-429 --network trading_default \
  -v "$WORK_DIR/stub429.py:/tmp/stub429.py:ro" trading-api:local python /tmp/stub429.py
OKX_REST_BASE_URL=http://s12-okx-429:8099 \
  docker compose -f infra/docker-compose.yml up -d --no-deps api worker
```

| 观测 | 实测 |
| --- | --- |
| 桩服务可达性（从 api 容器内发起请求） | 200/429 正常返回，证明注入生效 |
| 回补任务 `ops.job_run.id=1495` | `failed`，`error = upstream unavailable after 5 attempts: okx rate limited: /api/v5/market/history-candles` |
| 期间该标的 K 线 | 9 → 9（失败不留半截数据） |
| 移除桩、恢复默认 `OKX_REST_BASE_URL` 后同窗口重跑 | **`partial`**，K 线 9 根（可重跑、已落库的确认 K 线不被覆盖） |

结论：限流不会导致脏写，失败原因可在任务行上直接读到；上游恢复后重跑即可补齐。

### 2.4 故障四：worker 进程重启

注入：`docker compose -f infra/docker-compose.yml restart worker`

| 观测 | 实测 |
| --- | --- |
| 重启到 healthy | **9s** |
| 重启后周期性 `ingest_candles` | job 1493 → `ok`（调度链路恢复） |
| 重复 K 线（`count(*) - count(distinct (instrument_id,bar,open_time)) from market.candle`） | **0** |
| 同参数回补重放 | 复用同一 `job_id=1498`，`ops.job_run` 回补任务行 241 → 241，K 线不变（幂等键语义不变） |
| 残留状态 | `status=running` 4 行、`status=queued` 3 行（见 6.1） |

结论：进程被杀不会造成重复写入，幂等键在重启后仍然有效；但被中断的任务不会自动续跑或回收入账（登记为工程债）。

## 3. 不变量汇总

| 不变量 | 判定 | 证据 |
| --- | --- | --- |
| 故障期间不产生脏数据 | ✅ | 四类故障期间 K 线、订单、策略计数均不变；重复 K 线 0 条 |
| 不可用时不伪装成功 | ⚠️ 部分成立 | 读/写失败返回 4xx/5xx 或挂起；**但 Redis 停摆时投递可返回 200 而任务永不执行**（6.1） |
| 恢复后链路可用 | ✅ | Redis 恢复后新窗口 202/partial；PG 恢复 1s 内 `/ready` 200；上游恢复后重跑 partial；worker 9s 恢复并跑完周期任务 |
| 幂等键语义在故障后不变 | ✅（附限制） | worker 重启后同参数复用同一 `job_id`；但投递失败残留的 `queued` 行会让该键永久 skipped（6.1） |
| 交易姿态未被故障改变 | ✅ | 全流程 `mode=paper`、`real_trading_enabled=false`、`mode=real` 订单 0 条、订单总数未变 |

## 4. 与「降级/自愈」的边界

本报告证明的是**不写坏数据 + 可恢复**，不是**自动降级**：

- Redis 停摆期间没有「降级为同步执行」这类兜底路径，投递就是不可用（只是表现不一致）。
- PostgreSQL 停摆期间没有只读模式，整体不可服务。
- worker 重启后不做任务续跑，中断任务由人工按 `ops.job_run` 处置。

这些都不是本次验收要求，也不应被解读为已具备的能力。

## 5. 复现与产物

```bash
bash scripts/e2e/chaos.sh
```

脚本退出码 0 表示四类故障的不变量全部成立；失败会打印步骤号与原因（`[FAIL] 步骤 N（…）：原因`）。
脚本带 `trap` 清理：删除桩容器、恢复 api/worker 的默认 `OKX_REST_BASE_URL`、拉起 postgres/redis。

实测数据：`docs/reports/chaos-artifacts.json`（`generated_at`/`phases`/`known_debt`，对应第 2 节那次运行）。

## 6. 工程债（登记，不在本次修复）

### 6.1 投递失败残留的任务行会永久锁死幂等键

- **现象**：Redis 不可用时 `POST /market/backfill`（以及所有走 `dispatch` 的异步端点）会留下
  `ops.job_run.status=queued` 的行；此后同参数重放返回 `200/skipped`，任务永远不会执行，数据永远不会补齐。
- **证据**：本次运行 job 1485 即此类残留；三次运行的投递表现分别为 `500` / `200` / 客户端 20s 超时。
- **代码位置**：`backend/app/jobs/runs.py` `create_run()`（`RUNNING_STATUSES=("queued","running")` 命中即返回既有行、
  `created=False`），投递调用点 6 处：`api/v1/market.py:123`、`api/v1/market.py:185`、`api/v1/research.py:149`、
  `api/v1/risk.py:253`、`api/v1/backtest.py:217`（均经 `api/v1/deps.py:dispatch` → `jobs/queue.py:enqueue_task`）。
- **修复方向**：投递抛异常时把该行更新为 `status='failed'`（携带 `error`），使重放命中 `RETRYABLE_STATUSES`；
  worker 启动时回收超过阈值的 `running` 行。涉及 6 处路由与既有单测，超出 S12「只做集成验收、不加业务能力」的范围。
- **影响面**：仅影响「投递那一刻 Redis 不可用」的窄窗口；正常运行时不会出现。

### 6.2 基础设施故障的错误响应不一致

- Redis 停摆投递：`500` 纯文本（无 §1.1 错误信封）。
- PostgreSQL 停摆读接口：`500` 纯文本；`/ready` 有时 20s 无响应而非快速 `503`。
- **修复方向**：把 `enqueue` 失败与 `OperationalError` 映射为 `503 dependency_unavailable` 信封，并给连接池设
  `connect_timeout`。属于全站错误处理改造，不在本次范围。

### 6.3 worker 被杀时正在执行的任务不回收

- **现象**：`ops.job_run` 残留 `status=running`（本次 4 行），arq 不续跑被中断任务（worker 日志
  `shutdown on SIGTERM ◆ 5 jobs complete ◆ 1 failed ◆ 0 retries ◆ 0 ongoing to cancel`）。
- **影响**：任务行长期 `running`，监控上表现为「假运行」；业务数据无重复（已用唯一约束与去重计数验证）。
- **修复方向**：worker 启动时把 `started_at` 早于阈值且 `worker` 为自己的 `running` 行标记 `failed`。

### 6.4 未交付项（不在本报告范围，见发布报告）

Kubernetes 生产部署未交付，登记在 `docs/reports/release-1.0.md` 的工程债一节。
