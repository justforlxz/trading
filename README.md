# trading

自托管的自动化交易系统：以标的之间的关系为主线发现机会、构建多空组合，并通过独立的风控与执行系统在 OKX 上交易美股相关合约。

**当前状态：v2 骨架。** v1 实现已整体移除（`v1-final` tag 可回溯），仓库只有能启动的空壳：单进程 FastAPI + 同步 SQLAlchemy + SQLite。业务逻辑随后续节点逐个接入。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.12+、FastAPI、同步 SQLAlchemy |
| 存储 | SQLite 单文件库（WAL 模式），无独立数据库进程 |
| 任务 | 进程内定时任务，不使用消息队列 |
| 前端 | TypeScript、React、Vite、Tailwind CSS、shadcn/ui 风格基础件 |

单进程部署：一个 `uvicorn` 进程同时提供 HTTP API 与静态前端产物，没有第二套运行时。

## 快速开始

```bash
cp .env.example .env      # 环境变量清单；默认值可直接跑
make install              # 建 .venv、安装后端（可编辑）与前端依赖
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
    main.py         应用装配：lifespan 建表 → 挂载路由
    config.py       环境变量解析（pydantic-settings）
    db/             同步引擎、会话、声明基类、建表入口
    api/            HTTP 协议层（无领域逻辑）
    shared/         跨域共享的纯函数（bar 周期等）
    market/         行情：K 线对齐、缺口、相关性
    backtest/       回测：成本模型、绩效指标
    indicators/ instrument/ watchlist/ strategy/ risk/ execution/ journal/ exchange/ jobs/
                    各域骨架，随对应阶段落地
  tests/            pytest（tests/api/ 起按接口分目录）
frontend/
  src/pages/        概览 / 自选 / 策略 / 回测 / 交易 / 设置
  src/components/   ui（基础件）与 layout（外壳）
  src/lib/          API 客户端、主题与纯展示工具
```

## 数据

库文件固定在 `backend/data/trading.db`，随首次启动由 `init_db()` 创建（`create_all`，幂等），并设置 `journal_mode=WAL`。该目录不进版本库。

## 门禁

```bash
make lint     # ruff check + ruff format --check + eslint
make test     # pytest + tsc --noEmit && vite build
make verify-live   # 起真实 uvicorn 进程并请求 /api/health
```

工程约定见 `AGENTS.md`。
