# AGENTS.md — trading 工程规范

本文件是仓库内**唯一的工程约定**。产品与阶段定义在 `docs/prd/v2.md`（由文档节点回写）；
与本文件冲突时，产品文档优先，并在 PR 中说明。

## 1. 目录约定

单进程**三层模块化单体**：`app/core` 叶子层 / 业务模块 / `app/api` 装配层。分层规则见 §2。

```
backend/            Python 3.12+ + FastAPI，单包
  app/
    main.py         应用装配：lifespan 执行迁移 → 挂载路由
    config.py       环境变量解析（pydantic-settings）
    core/            跨模块叶子层：错误、值对象、端口（不依赖任何业务模块）
    db/             引擎、会话、声明基类、迁移入口
    api/            对外 HTTP 协议层（无领域逻辑）
    shared/         跨域共享的纯函数（bar 周期等）
    market/         行情：K 线对齐、缺口、相关性
    backtest/       回测：成本模型、绩效指标
    indicators/ instrument/ watchlist/ strategy/ risk/ execution/ journal/ exchange/ jobs/
                    各域骨架，随对应阶段落地
  tests/            pytest，按接口/模块建子目录
  migrations/       Alembic 迁移脚本（表结构的唯一来源）
frontend/           React + TS + Vite + Tailwind
  src/pages/        概览 / 自选 / 策略 / 回测 / 交易 / 设置
  src/components/   ui（基础件）与 layout（外壳）
  src/lib/          API 客户端、主题、纯展示工具
```

- 不在仓库根新建第二个后端/前端目录；一个 Monorepo，一个后端包。
- 不建与当前阶段无关的目录或空接口；骨架目录只放 `__init__.py` 的一行说明。

## 2. 分层与依赖方向

三层结构与本层之间的依赖方向：

1. `app/core` 叶子层：错误类型、值对象、端口。每个模块都可以依赖它，它不依赖任何业务模块（由 `backend/tests/architecture/test_core_is_leaf.py` 把关）。
2. 业务模块：`market` / `instrument` / `watchlist` / `indicators` / `strategy` / `backtest` / `risk` / `execution` / `journal` / `exchange` / `shared`。逐条依赖边登记在 `backend/tests/architecture/test_import_graph.py` 的 `ALLOWED_DEPS`，未登记的依赖边即失败。
3. `app/api` 与 `jobs` 是装配层：`api` 是对外 HTTP 协议层，无领域逻辑；`jobs` 是进程内定时任务的装配，按 `ALLOWED_DEPS` 可依赖全部业务模块。

`db` 只被域模块使用；`config` 与 `core` 是基础设施叶子，任何模块都可依赖。

- 禁止：任何模块 `→ api`；`shared` 依赖任何业务模块；`market` 反向依赖 `strategy` / `execution`。
- 类别差异（`SPOT` / `SWAP`）只允许出现在 `instrument`（按类别交易规则集合的唯一真源）、`exchange`、`execution` 三个目录；其他模块一律查表取值，不写散落的 `inst_type` 分支（由 `backend/tests/architecture/test_no_inst_type_branch.py` 把关）。
- 业务计算只写成纯函数（无 IO、可直接断言）；编排层只做 IO 与事务边界。
- 单进程部署：没有独立 worker / scheduler / 消息队列，定时任务跑在同一进程内。
- 领域对象与表定义放在各自域目录，不建全局 `models.py`。

## 3. 命名

- 数据库：表名小写复数、无前缀；字段 `snake_case`；时间后缀 `_at`（时刻）/`_time`（K 线边界）/`_date`（本地业务日）。
- API：路径 `kebab-case`（`/api/health`），JSON 字段 `snake_case`，时间 ISO-8601 UTC 带 `Z`，`Decimal` 以字符串返回。
- Python：模块、函数、变量 `snake_case`；类 `PascalCase`；常量 `UPPER_SNAKE`。
- 前端：组件文件 `kebab-case.tsx`，导出组件 `PascalCase`；页面组件放 `pages/`，可复用件放 `components/ui/`。
- bar 枚举固定 `1m/5m/15m/1h/4h/1d`；上游 bar 写法（`1H`/`1D` 等）的映射只允许出现在交易所适配层。

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
- `scope` 取目录或模块名（`backend`、`frontend`、`docs`、`api`）。
- 一个任务一个 commit；同一任务的后续修复用 `git commit --amend`，不新增 commit。
- `Closes <MKACG-N>` 必须单独成行，供 Multica 关联关闭。
- 禁止 `--amend` 到别人的 commit、禁止强推共享分支。

## 5. 测试要求

- 新增或修改业务逻辑必须带测试；纯函数（相关性、成本、指标）必须有「已知答案」用例。
- 测试默认不连真实交易所、不发真实订单；外部响应必须用录制的真实 fixture。
- 每个测试用例用一个独立的 PostgreSQL schema（同一本地库内建、用完即删），不共享表，也不碰业务 schema；表结构由 Alembic 迁移建出。
- 门禁命令（提交前必跑，等价于 `make lint && make test`）：

```bash
make db-up   # 测试库要先起来（podman run）；容器已存在时只启动
cd backend && ../.venv/bin/python -m ruff check . \
  && ../.venv/bin/python -m ruff format --check . \
  && ../.venv/bin/python -m pytest -q
pnpm --dir frontend lint && pnpm --dir frontend build
```

## 6. 禁止事项

- 禁止业务逻辑写进 `api/` 或组件里；前端不做派生计算，所有派生值由后端返回。
- 禁止把密钥、`.env`、真实账户凭据提交进仓库；配置只经环境变量注入。
- 禁止用 Mock 数据伪装功能已完成；占位页面只能写「计划交付什么」，不得展示编造的业务数值。
- 禁止生产代码里出现 mock 常量或假数据分支。
- 禁止为「以后可能需要」新增抽象层；`ports` / 适配器层在出现第二个外部实现时才引入。
- 禁止兼容层、双写与 feature flag：旧实现直接删除，不做并行保留。
- 禁止绕过 `init_db()` 手改表结构；表结构变更随版本化迁移一起引入。
- 禁止大范围回滚与格式化无关文件（`git reset --hard`、全仓 `--fix` 到未改动文件）。

## 7. 本地开发

```bash
cp .env.example .env        # 环境变量清单；默认值可直接跑
make install                # 建 .venv，安装后端与前端依赖
make db-up                  # 用 podman run 起本地 PostgreSQL（已存在则启动）
make migrate                # 表结构推进到最新版本（alembic upgrade head）
make test                   # 后端 pytest + 前端构建
make lint
make format
make verify-live            # 起真实 uvicorn 进程并请求 /api/health
```

后端以 `backend/` 为 cwd 启动（`uvicorn app.main:app`）；数据库地址来自 `DATABASE_URL`，
与 cwd 无关。部署方式不在项目范围，本地数据库只用 `podman run` 起容器。

## 8. 文档与 issue 的关系

- 需求与计划只写在项目文档里：产品范围与功能状态在 `docs/prd/v6.md`，交付计划、阶段、依赖、接口契约和删除规则在 `docs/prd/v6-delivery.md`，已确认规格在 `docs/prd/v6-data-spec.md`。
- issue 只写本次执行范围、依赖、验收和状态，不复制文档正文，也不另建第二份状态表。
- 接口、依赖或计划变更时，先改文档并合并，再修改或创建 issue；PR 中写明受影响的 issue。
- 文档与 issue 冲突时以文档为准；文档与 `docs/prd/v6-data-spec.md` 冲突时以规格为准。
- 每次执行 issue 完成时，在同一个 PR 更新 `docs/prd/v6.md` 中自己负责的行。
