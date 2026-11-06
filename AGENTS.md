# AGENTS.md — trading 工程规范

本文件是仓库内**唯一的工程约定来源**。架构决策在 `docs/architecture/`，任务计划在 `docs/plan/p1.md`；
两者与本文件冲突时，架构文档优先，并在 PR 中说明。

## 1. 目录约定

```
backend/            Python 3.12 + FastAPI，单包多入口
  app/
    config.py       环境变量解析（pydantic-settings）
    db/             引擎、会话、声明基类
    api/v1/         对外 HTTP 协议层（无领域逻辑）
    ops/            健康/就绪与运维视图
    jobs/           arq 任务、worker 与 scheduler 入口、幂等键
    ports/          外部依赖协议（S3 起）
    adapters/       外部 IO 实现（S3 起）
    market/ research/ opportunity/ strategy/ backtest/   业务模块（S3 起）
  alembic/          迁移；`alembic upgrade head` 是唯一入口
  tests/            pytest，按业务模块建子目录
frontend/           React + TS + Vite + Tailwind + shadcn/ui
  src/pages/        概览 / 研究 / 策略 / 设置
  src/components/   ui（基础件）与 layout（外壳）
  src/lib/          主题、纯展示工具
infra/              docker-compose.yml、.env.example
```

- 仓库根 `compose.yaml` 只做 `include: infra/docker-compose.yml`，让根目录 `docker compose up` 可用。
- 不在仓库根新建第二个后端/前端目录；一个 Monorepo，一个后端包。

## 2. 分层与依赖方向

`adapters → ports ← core`，`services` 组合三者，`api`/`jobs` 只做协议编排。

- 禁止：`analysis → strategy`、`strategy → backtest`、`core → adapters`、任何模块 `→ api`、服务之间互调 service。
- 业务计算只写在 `*/core/` 的纯函数里；service 层只做编排与 IO。
- 服务进程（api/worker/scheduler）之间**没有 HTTP 契约**，只经 PostgreSQL 与 Redis 协作。
- P1 不建 `risk/`、`execution/`、`ai/` 目录，也不预留空接口。

## 3. 命名

- 数据库：schema 分域（`market`/`research`/`opportunity`/`strategy`/`backtest`/`ops`），表名小写复数、无前缀；字段 `snake_case`；时间后缀 `_at`（时刻）/`_time`（K 线边界）/`_date`（本地业务日）。
- API：路径 `kebab-case`（`/market/sync-status`），JSON 字段 `snake_case`，时间 ISO-8601 UTC 带 `Z`，`Decimal` 以字符串返回。
- Python：模块、函数、变量 `snake_case`；类 `PascalCase`；常量 `UPPER_SNAKE`。任务名 `verb_object`（`sync_instruments`、`ingest_candles`）。
- 前端：组件文件 `kebab-case.tsx`，导出组件 `PascalCase`；页面组件放 `pages/`，可复用件放 `components/ui/`。
- bar 枚举固定 `1m/5m/15m/1h/4h/1d`；OKX 的 `1H/4H/1D` 映射只允许出现在 `adapters/okx`。

## 4. 提交信息

```
<type>(<scope>): <english description, ≤72 chars>

<english body, 每行 ≤80>
<中文 body，与英文成对>

Log: <中文一行摘要>
Issue: Closes <MKACG-N>
Influence: <对系统/用户的影响>
```

- `type` 取 `feat|fix|refactor|test|docs|chore|perf|build|ci`。
- `scope` 取目录或模块名（`backend`、`frontend`、`infra`、`docs`、`ci`、`api`）。
- 一个任务一个 commit；同一任务的后续修复用 `git commit --amend`，不新增 commit。
- `Closes <MKACG-N>` 必须单独成行，供 Multica 关联关闭。
- 禁止 `--amend` 到别人的 commit、禁止强推共享分支。
- 每个 PR 描述必须列出**实际执行的验收命令与结果摘要**，不接受「应该能跑」。

## 5. 测试要求

- 新增或修改业务逻辑必须带测试；纯函数（相关性、权重、成本、指标）必须有「已知答案」用例。
- 测试分层：`unit`（纯函数，无 IO）、`integration`（ASGI 传输层 / 临时库）、`e2e`（Compose 内全链路）。
- 测试默认不连真实交易所、不发真实订单；外部响应必须用**录制的真实 fixture**，禁止手写「看起来合理」的行情。
- 门禁命令（提交前必跑，等价于 `make lint && make test`）：

```bash
cd backend && ruff check . && ruff format --check . && pytest -q
cd frontend && pnpm lint && pnpm build
docker compose config --quiet
```

  后端部分也可用 `make lint` / `make test` 在 `api-dev` 镜像内执行（同一份源码，挂载工作区）；前端部分始终在宿主机用 `pnpm`。

## 6. 禁止事项

- 禁止业务逻辑写进 `api/` 或组件里；前端不做派生计算，所有派生值由后端返回。
- 禁止把密钥、`.env`、真实账户凭据提交进仓库；配置只经环境变量注入。
- 禁止在 P1 引入下单、持仓、风控执行代码。
- 禁止用 Mock 数据伪装功能已完成；占位页面只能写「计划交付什么」，不得展示编造的业务数值。
- 禁止绕过 Alembic 手改表结构；禁止 `DROP` 生产数据。
- 禁止为「以后可能需要」新增抽象层或空壳模块。
- 新增依赖或容器必须在 PR 说明理由，并同步更新 `docs/architecture/` 对应文档。
- 禁止大范围回滚与格式化无关文件（`git reset --hard`、全仓 `--fix` 到未改动文件）。

## 7. 本地开发

```bash
cp .env.example .env        # 环境变量清单；默认值可直接跑
make up                     # 构建并启动六个服务，等待健康检查
make logs
make test                   # 后端 pytest（api-dev 容器）+ 前端 build（宿主机 pnpm）
make lint
make format
make down
```

`make up` 与 `make down` 可重复执行；`docker compose down -v && make up` 是可复现性判据。
`api-dev` 只在 `dev` profile 下存在，`docker compose up` 不会启动它，也不计入六容器。
