# trading

自托管的自动化交易系统：以标的之间的关系为主线发现机会、构建多空组合，并通过独立的风控与执行系统在 OKX 上交易美股相关合约。

**当前状态：v2 骨架。** v1 实现已整体移除（`v1-final` tag 可回溯），仓库只有能启动的空壳：单进程 FastAPI + 同步 SQLAlchemy + PostgreSQL。业务逻辑随后续节点逐个接入。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.12+、FastAPI、同步 SQLAlchemy |
| 存储 | PostgreSQL（本地用 podman 起一个容器），表结构走版本化迁移（Alembic） |
| 任务 | 进程内定时任务，不使用消息队列 |
| 前端 | TypeScript、React、Vite、Tailwind CSS、shadcn/ui 风格基础件 |

单进程部署：一个 `uvicorn` 进程同时提供 HTTP API 与静态前端产物，没有第二套运行时。

## 快速开始

```bash
cp .env.example .env      # 环境变量清单；默认值可直接跑（make db-up 也会按需生成）
make install              # 建 .venv、安装后端（可编辑）与前端依赖
make db-up                # 用 podman run 起本地 PostgreSQL
make migrate              # 把库结构推进到最新版本（alembic upgrade head）
make test                 # 后端 pytest + 前端构建
```

只跑后端：

```bash
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload
curl -s localhost:8000/api/health
```

只跑前端（开发服务器把 `/api` 反代到 `localhost:8000`）：

```bash
pnpm --dir frontend dev
```

## 目录

```
backend/
  app/
    main.py         应用装配：lifespan 执行迁移 → 挂载路由
    config.py       环境变量解析（pydantic-settings）
    db/             同步引擎、会话、声明基类、迁移入口
    api/            HTTP 协议层（无领域逻辑）
    shared/         跨域共享的纯函数（bar 周期等）
    market/         行情：K 线对齐、缺口、相关性
    backtest/       回测：成本模型、绩效指标
    indicators/ instrument/ watchlist/ strategy/ risk/ execution/ journal/ exchange/ jobs/
                    各域骨架，随对应阶段落地
  tests/            pytest（tests/api/ 起按接口分目录）
  migrations/       Alembic 迁移脚本（表结构的唯一来源）
frontend/
  src/pages/        概览 / 自选 / 策略 / 回测 / 交易 / 设置
  src/components/   ui（基础件）与 layout（外壳）
  src/lib/          API 客户端、主题与纯展示工具
```

## 数据

表结构只有一条产生路径：`backend/migrations/` 里的迁移脚本。应用启动（`init_db()`）、`make migrate`
与 `python -m alembic upgrade head` 执行的是同一条命令，已是最新版本时为空操作。

数据库地址来自环境变量 `DATABASE_URL`（清单见 `.env.example`），没有内建默认值。本地用
`make db-up` 起一个 podman 容器，`make db-down` 停止它（数据留在容器里）。测试不共享表：
每个用例在自己独有的临时 schema 里跑，用完即删。

## 门禁

```bash
make lint     # ruff check + ruff format --check + eslint
make test     # pytest + tsc --noEmit && vite build
make verify-live   # 起真实 uvicorn 进程并请求 /api/health
```

工程约定见 `AGENTS.md`。
