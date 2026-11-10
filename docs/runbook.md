# 运行手册（Runbook）

面向「自己部署自己维护」的单机部署。覆盖 部署 / 配置 / 备份恢复 / 升级回滚 / 故障排查 / 日志位置 六节，
所有命令都在 S12 验收时逐条执行过（见每节的「已验证」标注）。

前提：Linux 宿主机，Docker Engine ≥ 24 与 Docker Compose v2（`docker compose version` 可跑）；
仓库根执行；`pnpm` 只在跑前端门禁时需要，部署不需要。

## 1. 部署

### 1.1 首次部署（空目录）

```bash
git clone <repo> trading && cd trading
cp .env.example .env          # 至少改 POSTGRES_PASSWORD；实盘相关保持默认 false/空
make up                       # = docker compose up -d --build --wait
```

`make up` 会构建 `trading-api:local`（后端 runtime 目标）与 `trading-web:local`（前端静态站点），
起六个服务并等到健康检查全部通过才返回。首次构建约 2–4 分钟；之后走层缓存。

数据卷：`pgdata`（PostgreSQL 数据，唯一真相）、`redisdata`（队列/缓存，可丢）。

### 1.2 验收部署是否成功

```bash
docker compose ps                                             # 六个服务 running + healthy
curl -s localhost:8000/health                                  # {"status":"ok","version":"0.1.0"}
curl -s localhost:8000/ready                                   # 依赖就绪（db/redis 可用）
docker compose exec -T api alembic current                     # 0009_mcp_schema (head)
curl -s -o /dev/null -w '%{http_code}\n' localhost:5173        # 前端 200
```

**已验证（2026-11-10）**：从 `git clone` 出来的空目录执行 `cp .env.example .env && make up`，
六服务 healthy，`/health` 200 `{"status":"ok","version":"0.1.0"}`，`alembic current` = `0009_mcp_schema (head)`，
前端 200。

### 1.3 端口与访问

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| 8000（`API_PORT`） | api | REST `/api/v1/**` + MCP `/mcp` + `/health`、`/ready` |
| 5173（`WEB_PORT`） | web | 前端静态站点（nginx） |
| — | postgres / redis | 不发布端口，只在 compose 内网可达 |

生产化的第一件事是在前面加一层 TLS 反向代理；仓库不自带网关（见 `docs/reports/release-1.0.md` 工程债）。

### 1.4 停止与清理

```bash
make down                                         # 停容器，保留 pgdata/redisdata
docker compose down -v                            # 连数据卷一起删（等价于重置为干净库）
```

`docker compose down -v && make up` 是本仓库标准的「干净库验收」起手式，见 `scripts/e2e/full_smoke.sh`。

## 2. 配置

唯一配置入口是仓库根的 `.env`（内容模板为 `.env.example`，是 `infra/.env.example` 的软链）。
**不要**把 `.env` 提交进仓库；密钥只从这里注入。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `APP_ENV` | `dev` | 运行环境标识（`dev`/`ci`/`prod`） |
| `LOG_LEVEL` | `INFO` | 后端日志级别 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `trading` / `change-me-in-production` / `trading` | 数据库账号与库名；生产必须改密码 |
| `REDIS_URL` | `redis://redis:6379/0` | 队列与缓存；不是唯一真相 |
| `API_PORT` / `WEB_PORT` | `8000` / `5173` | 宿主机映射端口 |
| `OKX_REST_BASE_URL` | `https://www.okx.com` | 公共行情上游；只在故障注入时指向桩服务 |
| `SCHEDULER_HEARTBEAT_INTERVAL_SECONDS` | `5` | scheduler 心跳写入间隔 |
| `SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS` | `30` | 超过此时长无心跳即判定 scheduler 失联 |
| `REAL_TRADING_ENABLED` | `false` | 实盘总闸；非 `true` 时任何真实下单 403 |
| `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE` | 空 | OKX 私有接口凭据；空即无法真实下单 |
| `EXECUTION_REAL_STRATEGY_IDS` | 空 | 实盘逐策略放行清单（逗号分隔 `strategy.id`），空表示一个都不放行 |
| `EXECUTION_PAPER_FILL_CHUNKS` | `0.5,0.5` | paper 撮合分段比例（两段模拟部分成交） |
| `EXECUTION_STOP_LOSS_RATIO` | `0.05` | 自动止损阈值（单腿浮亏/持仓均价） |

改配置的流程：编辑 `.env` → `make up`（compose 会重建受影响的容器）→ 复验 1.2。
**改 `POSTGRES_PASSWORD` 不会改已有数据卷里的密码**：数据卷里的角色密码是初始化时写死的，
换密码要么改库内角色（`ALTER ROLE`），要么重建数据卷（会丢数据）。

实盘开关的三重前提（缺一不可，任缺即 403）：`REAL_TRADING_ENABLED=true`、OKX 三个凭据齐全、
目标策略 id 在 `EXECUTION_REAL_STRATEGY_IDS` 里。三项默认值全是「关」，因此默认部署**不可能**下真单。

## 3. 备份与恢复

### 3.1 备份

```bash
docker compose exec -T postgres pg_dump -U trading -d trading -Fc > trading-$(date +%F).dump
```

自定义格式（`-Fc`）体积小、可选择性恢复。全库约 1.4 MB（1.0 交付时 543 标的、3.5 万根日线）。
建议每日一次，加进宿主机 cron；备份文件放仓库目录之外。

Redis 不需要备份：队列丢了只会重跑任务，`ops.job_run` 会记录重跑；缓存丢了直接回源。

### 3.2 恢复

```bash
docker compose exec -T postgres psql -U trading -d postgres -c 'drop database if exists trading_restore'
docker compose exec -T postgres psql -U trading -d postgres -c 'create database trading_restore'
docker compose exec -T postgres pg_restore -U trading -d trading_restore --no-owner < trading-2026-11-10.dump
# 校验：行数与版本
docker compose exec -T postgres psql -U trading -d trading_restore -At -c 'select count(*) from market.instrument'
docker compose exec -T postgres psql -U trading -d trading_restore -At -c 'select version_num from alembic_version'
```

**已验证（2026-11-10）**：`pg_dump -Fc` 产出 1.4 MB，`pg_restore --no-owner` 到新库退出 0，
`market.instrument` 543 行，`alembic_version` = `0009_mcp_schema`。

线上回切：`docker compose stop api worker scheduler` → 把恢复好的库改成正式库名（或把 `POSTGRES_DB`
指向恢复库）→ `make up` → 复验 1.2。**先停写方再换库**，避免恢复库被继续写入后又覆盖回去。

## 4. 升级与回滚

### 4.1 升级

```bash
docker compose exec -T postgres pg_dump -U trading -d trading -Fc > pre-upgrade.dump   # 1. 先备份
git fetch && git checkout <新版本 tag 或 commit>                                      # 2. 换代码
make up                                                                                # 3. 重建 + 迁移
curl -s localhost:8000/health && docker compose exec -T api alembic current            # 4. 复验
```

迁移由 api 容器启动时自动执行（`RUN_MIGRATIONS=1`，entrypoint 里 `alembic upgrade head`，幂等）；
也可以单独跑 `make migrate`。迁移链是 0001 → 0009 单向线性，`alembic current` 必须等于 `(head)`。

### 4.2 回滚

回滚分两层，**都要求「先备份、先停写」**。

代码回滚（不改数据库结构，最常用）：

```bash
docker compose stop api worker scheduler      # 停写方，避免旧代码写新结构
git checkout <上一个可用 commit 或 tag>
make up
curl -s localhost:8000/health
```

带结构回滚（新版本引入的迁移要撤销）：

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 api alembic downgrade -1   # 回退一版
docker compose run --rm -e RUN_MIGRATIONS=0 api alembic current        # 确认版本号
# 再按上面「代码回滚」换回旧代码并 make up
```

若回退涉及数据形态变化（列被删、语义变了），不要用 `downgrade` 硬退，改用第 3 节的备份恢复：
`downgrade` 只保证结构可逆，不保证数据可逆。

**已验证（2026-11-10）**：空库上 `alembic upgrade head` 17.7 秒到达 `0009_mcp_schema`；
`alembic downgrade -1` 回到 `0008_execution_schema`，再 `upgrade head` 回到 `0009_mcp_schema`，链路可逆。

本仓库目前**没有 git tag**（1.0 尚未打标）。发布时应在合并提交上打 `v1.0.0`（由 PL 执行），
此后回滚命令里的 `<tag>` 才有意义。

## 5. 故障排查

先看三件事：`docker compose ps`（谁不健康）、`curl -s localhost:8000/ready`（依赖是否就绪）、
`docker compose logs --tail=100 api worker scheduler`（最近错误）。

| 症状 | 判定 | 处置 |
| --- | --- | --- |
| `api` healthcheck 一直不通过 | 启动即崩：迁移失败或 `DATABASE_URL` 错 | `docker compose logs api`；修 `.env` 后 `make up` |
| `/health` 200 但 `/ready` 503 `dependency_unavailable` | DB 或 Redis 不可达（`/health` 是存活探针，故意不查依赖） | 先起依赖：`docker compose start postgres redis`；`/ready` 恢复通常 1 秒内（连接池 `pool_pre_ping`） |
| Redis 挂了，`POST /market/backfill` 返回 **500 `Internal Server Error`**（无错误信封） | 派发队列不可用；`ops.job_run` 里会留一条永远 `queued` 的行 | 起 Redis 后**换一组参数**重试（见下行）；这是一条已知工程债：派发失败没有把 run 标成 `failed` |
| 同一组参数重放返回 `200` + `status:"skipped"`，但数据没进来 | 上一轮派发失败留下的 `queued`/`running` 行占住了幂等键（`ops.job_run` 对 `(job_name, job_key)` 唯一） | `docker compose exec -T postgres psql -U trading -d trading -c "update ops.job_run set status='failed', error='orphaned' where status in ('queued','running') and job_name='backfill_candles'"`，然后重放；排查记录见 `docs/reports/chaos-report.md` §6.1 |
| worker 重启后某些 `ops.job_run` 永远 `running` | arq 不恢复被 kill 的在途任务 | 同上手工收尾；不影响新任务执行（重启后新任务照常 `ok`） |
| 任务 `failed` 且 `error` 含 `okx rate limited` / `429` | 上游限流，已按 5 次重试退避后失败 | 等几分钟重放；重放会复用同一 `job_key`（`failed`/`partial` 可重试） |
| scheduler 心跳告警（`SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS` 30 秒无更新） | scheduler 进程挂了或卡住 | `docker compose restart scheduler`；再不行看 `docker compose logs scheduler` |
| MCP 调用返回 401 `mcp_unauthorized` | 令牌错、已吊销或客户端不存在 | 新建客户端取新令牌（令牌只在创建时返回一次）；`GET /api/v1/mcp/clients` 看 `revoked_at` |
| MCP 调用返回 403 `mcp_forbidden` | 令牌作用域是 `read`，却调了操作类工具（`trigger_scan`/`create_strategy_draft` 等） | 需要操作能力就新建 `scopes:["operate"]` 的客户端；`mcp.mcp_call_log` 里有对应审计行 |
| 真实下单 403 `real_trading_disabled` | `REAL_TRADING_ENABLED` 不是 `true` | 这是**预期行为**。确有实盘需求时才按第 2 节三重前提放行，并逐策略确认 |
| 真实下单 403 `execution_credentials_missing` / `execution_strategy_not_authorized` | 凭据没配 / 策略不在放行清单 | 补 `OKX_API_*`，把 `strategy.id` 加进 `EXECUTION_REAL_STRATEGY_IDS` |
| 前端白屏 | 后端不可达或静态资源没构建 | `curl -s -o /dev/null -w '%{http_code}\n' localhost:5173`；`docker compose logs web`；`pnpm --dir frontend build` |
| 磁盘持续增长 | 镜像层与容器日志 | `docker system df`；`docker compose down` 后清旧镜像；日志轮转见第 6 节 |

**先停写再动手**：任何涉及数据库的处置，先 `docker compose stop api worker scheduler`。

## 6. 日志位置

| 位置 | 命令 | 内容 |
| --- | --- | --- |
| 容器标准输出（主入口） | `docker compose logs -f --tail=100 api` | 后端结构化日志（`LOG_LEVEL` 控制级别） |
| 按时间窗 | `docker compose logs --since 30m api worker` | 排查「刚才那次」失败 |
| 单服务 | `docker compose logs scheduler` | 心跳与周期任务派发记录 |
| 宿主机 json-file | `docker inspect --format '{{.LogPath}}' trading-api-1` | 容器日志文件实体（默认 `json-file` 驱动，无轮转上限） |
| 数据库侧 | `docker compose exec -T postgres psql -U trading -d trading -c "select * from ops.job_run order by id desc limit 20"` | 任务派发/执行结果（`status`、`attempts`、`error`、`result`） |
| 审计 | `... -c "select * from ops.audit_log order by id desc limit 20"` | 业务写操作审计 |
| MCP 调用 | `... -c "select * from mcp.mcp_call_log order by id desc limit 20"` | 每次 MCP 调用（工具名、状态、错误码、耗时） |
| 风控事件 | `... -c "select * from risk.risk_event order by id desc limit 20"` | 限额/回撤/资金费率等 breach 记录 |

日志默认用 Docker 的 `json-file` 驱动，**没有配置轮转上限**，长期运行需要宿主机侧配置
`/etc/docker/daemon.json` 的 `log-opts`（`max-size`/`max-file`），或改用集中式日志采集。
应用自身只写 stdout，不写文件；排查历史问题优先查数据库里的 `ops.job_run` / `ops.audit_log` /
`mcp.mcp_call_log`——它们比日志更可靠，且不依赖日志是否被轮转掉。

## 附录：常用命令速查

```bash
make help                 # 列出全部目标
make up / down / logs     # 启停与跟踪日志
make migrate              # 单独执行 alembic upgrade head（幂等）
make lint / test / coverage   # 后端 ruff + pytest（容器内）、前端 lint/build
bash scripts/e2e/full_smoke.sh    # 全链路一键验收（需干净库）
bash scripts/e2e/chaos.sh         # 四类故障注入验收
bash scripts/e2e/security_audit.sh # 安全审计探针（只读；逐项断言，非 paper 姿态直接中止）
```
