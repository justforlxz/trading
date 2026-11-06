# trading

自托管的自动化量化交易系统：分析美股之间的动态相关性、市场共振、趋势与相对强弱，构建多空组合策略，在 OKX 美股 USDT 本位永续合约上执行。

> 当前仓库只有工程骨架与设计文档，**没有业务实现**。功能从 S3 起按 `docs/plan/p1.md` 的任务顺序推进。

## 当前阶段

**P1 交易前准备 · S2 Monorepo 工程骨架与部署基线（已完成）**

| 项 | 状态 |
| --- | --- |
| 技术栈 | Python 3.12 + FastAPI / SQLAlchemy async + Alembic；React 18 + Vite + TS + Tailwind + shadcn/ui；PostgreSQL 16 + Redis 7；arq（worker + scheduler） |
| 运行时形态 | Docker Compose 六服务：`postgres`、`redis`、`api`、`worker`、`scheduler`、`web` |
| 已可运行 | `/health`、`/ready`、`/api/v1` 前缀、前端四路由与双主题、`alembic upgrade head`、arq 任务链路、CI |
| 阶段范围 | 行情采集、股票关系分析、全市场机会发现、策略生成与审批、历史回测与评估 |
| 明确不做 | 模拟交易、真实下单、风控执行、AI 参与交易决策（P2/P3/P4） |
| 待决策 | 3 项，见 `docs/risk/external-dependencies.md` §5 |

## 快速开始

```bash
cp .env.example .env          # 环境变量清单；默认值可直接跑，密钥不入库
make up                       # 构建并启动六个服务，等待健康检查通过
curl -fsS localhost:8000/health   # {"status":"ok","version":"0.1.0"}
curl -fsS -o /dev/null -w '%{http_code}\n' localhost:5173   # 200
make logs
make down
```

也可直接使用 Compose（与 `make up` 等价）：

```bash
docker compose up -d --build --wait
docker compose ps --format json
```

**可复现性判据**：`docker compose down -v && make up` 从零重建后，上述两个探活命令仍成立。

### 容器与端口

| 服务 | 作用 | 端口 |
| --- | --- | --- |
| `postgres` | 唯一持久化真相（schema 分域） | 仅内网 |
| `redis` | 任务队列与短期缓存 | 仅内网 |
| `api` | 同步请求；启动时幂等执行 `alembic upgrade head` | 8000 |
| `worker` | 执行 arq 任务，不对外暴露端口 | — |
| `scheduler` | 按 cron 与市场时段投递任务（同一镜像、独立进程） | — |
| `web` | 静态资源、SPA 路由回退、`/api` 反代 | 5173 |

### 存活探针

```bash
# scheduler：Redis 心跳新鲜度（退出码 0 = 存活）
docker compose exec -T scheduler python -m app.jobs.probe scheduler

# worker：确认 arq 进程存在（退出码 0 = 存活）
docker compose exec -T worker python -m app.jobs.probe worker

# 就绪：数据库可连通才返回 200
curl -fsS localhost:8000/ready
```

上述两条探针同时是 Compose 的 `healthcheck`，因此 `docker compose ps` 里的 `running` 与 `healthy` 是同一判据。

### 本地校验矩阵

```bash
cd backend && ruff check . && ruff format --check . && pytest -q
cd frontend && pnpm install --frozen-lockfile && pnpm lint && pnpm build
docker compose config --quiet
actionlint .github/workflows/ci.yml
```

`make test` / `make lint` / `make format` 的后端部分走 `api-dev` 镜像（`dev` profile，装齐 dev extras 并挂载工作区源码，跑的是当前工作树），因此不依赖本机 Python；前端部分在宿主机用 `pnpm` 执行，需要本机装有 pnpm。`make migrate` 对运行中的数据库执行迁移（会自动拉起依赖服务）。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| `AGENTS.md` | 工程规范：目录、分层、命名、提交信息、测试门禁、禁止事项 |
| `docs/architecture/overview.md` | 模块边界、依赖方向、运行容器与启动顺序、故障域 |
| `docs/architecture/data-model.md` | 实体、关键字段、唯一约束与幂等键、时间与精度约定 |
| `docs/architecture/api-contract.md` | 对外 REST 契约草案、错误与分页约定、实体↔资源映射 |
| `docs/plan/p1.md` | P1 任务拆解（依赖 / 交付物 / 验收命令 / 判据）与 S3–S8 映射 |
| `docs/risk/external-dependencies.md` | OKX 与美股行情源实测证据、结论、风险与待决策项 |
| `docs/architecture/adr/` | 架构决策记录 0001–0006 |

## 探针脚本

调研结论都可复现，脚本只读、无副作用、仅用 Python 标准库：

```bash
python3 scripts/probes/okx_probe.py all        # 合约清单 / 行情 / 资金费率 / 历史深度
python3 scripts/probes/equity_probe.py all     # 真实美股行情源可得性
python3 scripts/probes/okx_probe.py --help
python3 scripts/probes/equity_probe.py --help
```
