# 性能基线（MKACG-703 / S12-03）

**结论：单节点 Docker Compose 形态下，230 个美股永续标的的全池日线回补约 71 秒（3.2 任务/秒），
全市场机会扫描服务端耗时 3.2 秒（230 标的、203 个可分析），关键 GET 接口 p95 均在 13 ms 以内，
MCP 只读调用 p95 约 50 ms。本基线只用于容量判断与告警阈值取值，不构成 SLA 承诺。**

## 1. 环境与口径

| 项 | 值 |
| --- | --- |
| 运行日期 | 2026-11-10（UTC+8 凌晨，宿主机空闲） |
| 仓库基线 | `master@7dfe8cd`（S11 合并后，S12 集成验收期间） |
| 主机 | 12 vCPU / 39 GiB RAM，Linux，单机 Docker |
| 运行形态 | Docker Compose 六服务（`postgres`/`redis`/`api`/`worker`/`scheduler`/`web`），1 个 worker 进程、并发度 1 |
| 数据规模 | `market.instrument` 543 行（其中 `inst_category=3` 美股永续 230 个）；`market.candle` 35 741 行（1d 27 717 行占 3.5 MB）；数据库 26 MB |
| 上游 | OKX 公有 REST（`www.okx.com`），公网延迟未受控 |
| 采集方式 | `curl -w '%{time_total}'`，每接口 25 次**顺序**采样（无并发），取 p50/p95/max |
| 未覆盖 | 并发压测、长时间浸泡、多 worker 横向扩容、Kubernetes；见第 7 节 |

所有数字都是本机实测；「服务端耗时」取任务/运行记录里由服务端自己记的 `duration_ms`，「端到端耗时」取脚本
从派发到任务终态的墙钟时间。

## 2. 全池日线回补（`POST /market/backfill` × 230）

一次干净数据库上的一键验收（`bash scripts/e2e/full_smoke.sh` 步骤 1）：

| 指标 | 实测 |
| --- | --- |
| 标的池 | `inst_category=3` 的 **230** 个美股 USDT 永续（全库 543 个标的） |
| 回补参数 | `bar=1d`，窗口 `2025-06-01` → 今日（上游实际最早数据约 2026-03，故任务终态为 `partial`） |
| 端到端耗时 | **71 141 ms**（含 3 个失败任务的重试轮） |
| 吞吐 | **3.23 任务/秒**；单任务平均 0.31 s |
| 写入行数 | 首次填充 1d K 线 **27 717 行**（约 120 行/秒） |
| 二次运行 | 同参数重放耗时 72 345 ms（任务行复用、`attempts` 自增，上游 `partial` 属可重试终态故重新执行） |

结论：**日频全池回补约 1.2 分钟**，瓶颈在 OKX `history-candles` 的限流与单 worker 串行，不在数据库
（27.7k 行写入仅占 3.5 MB）。

## 3. 全市场机会扫描（`POST /opportunities/scan`）

| 指标 | 实测 |
| --- | --- |
| universe（参与标的） | **230** |
| analysed（有效分析） | **203**（27 个因数据不足被跳过，记录在 `counts.missing.insufficient_bars`） |
| 服务端耗时 `counts.duration_ms` | **3 244 ms** |
| 端到端耗时（派发 → 终态） | **4 238 ms** |
| 产出 | 49 个机会（9 方向性 + 40 相对价值），9 个聚类，市场广度 187 涨 / 43 跌 |

结论：扫描是单进程内的相关性/聚类计算，**耗时近似随 universe 线性增长（约 16 ms/标的）**；230 标的
规模下 3 秒级，不需要预计算缓存。

## 4. 关键 GET 接口延迟（25 次顺序采样）

| 接口 | p50 | p95 | max |
| --- | --- | --- | --- |
| `GET /health` | 0.0014 s | 0.0020 s | 0.0025 s |
| `GET /api/v1/market/instruments?limit=50` | 0.0064 s | 0.0112 s | 0.0128 s |
| `GET /api/v1/market/candles?inst_id=AAPL-USDT-SWAP&bar=1d&limit=300` | 0.0108 s | 0.0129 s | 0.0200 s |
| `GET /api/v1/opportunities?limit=20` | 0.0079 s | 0.0106 s | 0.0121 s |
| `GET /api/v1/strategies/1` | 0.0079 s | 0.0090 s | 0.0091 s |
| `GET /api/v1/backtests/1/metrics` | 0.0048 s | 0.0054 s | 0.0067 s |
| `GET /api/v1/execution/positions` | 0.0053 s | 0.0061 s | 0.0095 s |
| `GET /api/v1/risk/status?strategy_id=1` | 0.0100 s | 0.0124 s | 0.0148 s |
| `POST /mcp`（`tools/call` `get_strategy`，只读客户端） | 0.0318 s | 0.0495 s | 0.1015 s |

MCP 调用比同数据量的 REST 慢约 30 ms，差值是鉴权（sha256 token 查表）+ 调用审计写 `mcp.mcp_call_log`
的开销，属预期。

## 5. 采样脚本（可复现）

```bash
# 关键 GET：25 次顺序采样，输出 p50/p95/max
B=http://localhost:8000/api/v1
for i in $(seq 1 25); do
  curl -sS -o /dev/null -w '%{time_total}\n' "$B/market/candles?inst_id=AAPL-USDT-SWAP&bar=1d&limit=300"
done | sort -n | awk '{a[NR]=$1} END {printf "p50=%.4f p95=%.4f max=%.4f\n", a[int((NR-1)*0.5)+1], a[int((NR-1)*0.95)+1], a[NR]}'

# 全池回补 / 全市场扫描的耗时直接取一键脚本输出（scripts/e2e/full_smoke.sh 步骤 1、3）
bash scripts/e2e/full_smoke.sh
```

## 6. 容量判断与建议

| 结论 | 依据 |
| --- | --- |
| 日频全池回补可在 2 分钟内完成，不需要并发调度 | 230 任务 71 s，峰值 3.2 任务/秒 |
| 机会扫描在 500 标的以内仍是秒级 | 3.2 s / 203 标的 ≈ 16 ms/标的，外推 500 标的约 8 s |
| 当前不需要为读接口加缓存 | 最慢的 `risk/status` p95 12.4 ms，`market/candles` p95 12.9 ms |
| 数据库增长温和 | 1d K 线 27.7k 行 = 3.5 MB；五年日线≈ 8 MB/230 标的 |
| 扩展顺序应为「先加 worker 并发，再加分片」 | 回补瓶颈是上游限流 + 单 worker 串行；扫描瓶颈是单进程 CPU |

**未做**：并发压测、多 worker 实测、1m 全池回补（会撞 OKX 限流）、Kubernetes 下的资源画像。这些数据在
真实放量前必须补测。

## 7. 建议的告警阈值（与本次基线对齐）

配置名均取自代码现有字段，不新增配置项：

| 告警 | 数据源 | 建议阈值（基线 ×3 或既有配置项） |
| --- | --- | --- |
| 调度器心跳丢失 | `SCHEDULER_HEARTBEAT_INTERVAL_SECONDS=5` / `SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS=30`（`backend/app/config.py`），`/ready` 返回 503 | 超过 30 s 无心跳即告警（既有语义） |
| 就绪失败 | `GET /ready` | 连续 3 次非 200 |
| 任务卡死 | `ops.job_run.status IN ('queued','running')` 且 `started_at` 超过 15 min | 已知工程债：投递失败会残留 `queued`、进程被杀会残留 `running`（见 `chaos-report.md` 6.1/6.3），告警同时兼作人工回收触发器 |
| 回补变慢 | 单任务端到端耗时 | 基线 0.31 s，告警阈值 5 s；整池回补 > 10 min 即告警 |
| 扫描变慢 | `opportunity.opportunity_run.counts.duration_ms` | 基线 3 244 ms，告警阈值 30 s |
| 读接口变慢 | 反向代理/采集端 p95 | 基线 ≤ 13 ms，告警阈值 200 ms |
| 风控事件堆积 | `risk.risk_event`（`kind='limit_breach'`，未 `resolved_at`） | 单策略 1 h 内 > 10 条 |
| 交易姿态被改动 | `GET /execution/mode` 的 `mode` / `real_trading_enabled` | 非预期变为 `real`/`true` 即最高级别告警 |

告警通道本身不在本次交付范围（Kubernetes/监控栈未交付，见 `release-1.0.md` 工程债），上表只给出
「用什么指标、取什么阈值」。
