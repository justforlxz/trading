# ADR-0003：异步任务用 arq（Redis），而非同步计算或 Celery

- 状态：已接受
- 日期：2026-11-06
- 相关：`docs/architecture/overview.md` §5、`docs/plan/p1.md`

## 上下文

P1 的长任务：标的全量同步、K 线回补（受 40 req/2s 限流约束）、全市场扫描（≤5 分钟）、回测（可能数十秒到数分钟）。这些任务必须：可重试、可观测、与请求处理隔离、能按 cron 触发、支持幂等（同一 `as_of` 重跑不产生副本）。技术栈已经确定为 FastAPI + SQLAlchemy async + httpx。

## 决策

使用 **arq**：基于 Redis 的异步任务队列，worker 与 scheduler 与 API 同镜像不同进程。

- 任务签名带 `job_key`（参数规范化 JSON 的 sha256），落库前检查 `ops.job_run` 唯一键。
- 重试采用指数退避，最大尝试次数按任务类型配置；失败写 `error` 与 `attempts`。
- cron 由 arq 内建调度承担，`scheduler` 只负责投递（含市场时段判断），不执行重计算。
- Redis 只承载队列与短期缓存，不作为唯一真相：丢失后可从 DB 与外部源重建。

## 后果

正面：

- 与既有 async 栈同构：任务里可以直接 `await` httpx 与 SQLAlchemy async session，无需同步桥接。
- 部署轻：不需要单独的 broker 管理界面（Redis 已是 Compose 必需组件）。
- 幂等语义由 `job_run(job_name, job_key)` 唯一键强制，重启/重复投递都不会产生重复数据。

负面 / 代价：

- 生态与可观测性弱于 Celery（无 Flower 等成熟面板）；需自己用 `job_run` 表做运维视图。
- 不支持复杂工作流原语（chain/group/chord）；P1 的"投递 → 执行 → 落库"是单步链，够用。
- Redis 非持久化配置下，进程崩溃可能丢失队列中的任务；靠 `job_run` 的 `queued` 超时回收补齐。

## 为什么不是其它方案

| 备选 | 拒绝理由 |
| --- | --- |
| 在 API 请求内同步执行 | 扫描/回补会超过反代与客户端超时；进程重启即丢失；无法重试与限流 |
| Celery | 同步 worker 模型与 async SQLAlchemy/httpx 需要额外桥接（`asgiref`），且需额外 broker/结果后端配置；P1 不需要其工作流能力 |
| APScheduler + 自建线程池 | 无持久队列、无跨进程重试语义，多副本时会重复执行；等于自己实现一个更差的 arq |
| 数据库轮询队列（`SELECT ... FOR UPDATE SKIP LOCKED`） | 语义可行但需要自己写调度、重试、延迟投递；在没有 PG 专职运维的情况下，Redis 队列更简单 |

## 复核触发条件

出现真实的多步编排需求（例如 P2 的"扫描 → 风控预检 → 组合调整 → 通知"依赖链），或需要任务级进度推送与可视化；届时评估 Temporal（若允许新增服务）或 Celery + canvas，而不是在 arq 上自建 DAG。
