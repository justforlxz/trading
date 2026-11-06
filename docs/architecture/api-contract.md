# API 契约（P1 草案）

状态：**草案**。S3–S7 实现时可细化字段，但不得破坏本文的路径、错误信封、分页与异步任务约定；破坏性调整需在 PR 中说明并更新本文。

## 1. 通用约定

| 项 | 约定 |
| --- | --- |
| Base path | `/api/v1`（`/health`、`/ready` 不带版本前缀） |
| 传输 | JSON（`application/json; charset=utf-8`），字段 `snake_case` |
| 时间 | ISO-8601 UTC 字符串，带 `Z`：`2026-11-06T03:59:00Z` |
| 数值 | `Decimal` 一律以**字符串**返回：`"343.68"`；计数与布尔保持原生类型 |
| 鉴权 | P1 单用户自托管，**不做身份认证**；由部署侧绑定 `127.0.0.1`/内网。这是已知风险，见 `docs/risk/external-dependencies.md` §4 |
| 请求追踪 | 请求头 `X-Request-Id`（可选）；响应头回传；服务端生成 UUIDv4 兜底 |
| 幂等 | 写接口支持 `Idempotency-Key`；同 key 重复请求返回首次结果（`200`），不重复执行 |
| 分页 | 游标分页：`?limit=&cursor=`，`limit` 默认 50、上限 200；响应含 `next_cursor`（末页为 `null`） |
| 排序 | 列表默认按业务时间倒序（`-as_of`、`-created_at`），显式 `sort` 参数可覆盖。**例外（固定升序）**：`/market/candles`、`/market/equity-candles`、`/backtests/{run_id}/equity`、`/backtests/{run_id}/trades`，按时间升序返回以便直接绘图与逐笔核对 |
| 长任务 | 一律异步：返回 `202` + `Location: /api/v1/ops/job-runs/{id}`，客户端轮询任务状态 |

### 1.1 错误信封

所有非 2xx 响应统一为：

```json
{
  "error": {
    "code": "strategy_illegal_transition",
    "message": "cannot transition approved -> draft",
    "details": {"from": "approved", "to": "draft"},
    "request_id": "5f0c3a4e-..."
  }
}
```

| HTTP | `code` 示例 | 语义 |
| --- | --- | --- |
| 400 | `invalid_request` | 参数结构错误 |
| 404 | `not_found` | 资源不存在 |
| 409 | `duplicate_resource`、`strategy_illegal_transition`、`strategy_readonly` | 状态或唯一性冲突 |
| 422 | `validation_error` | 字段校验失败（附 `details.fields`） |
| 429 | `rate_limited` | 上游或自身限流 |
| 500 | `internal_error` | 未分类异常，不泄露堆栈 |
| 503 | `dependency_unavailable` | 数据库或外部源不可用 |

### 1.2 异步任务

所有 `202` 响应体：

```json
{"job_id": 12345, "status": "queued", "job_name": "scan_opportunities", "job_key": "9f1c..."}
```

任务状态查询：`GET /api/v1/ops/job-runs/{id}` → `queued|running|ok|failed|skipped`，`failed` 带 `error`。前端轮询间隔 ≥1s，`ok` 后按业务资源读取结果。

## 2. 实体与资源映射

实体名与 `docs/architecture/data-model.md` 一一对应，便于交叉检索与评审。

| 实体 | 资源 / 端点 |
| --- | --- |
| `instrument` | `GET /market/instruments`、`GET /market/instruments/{inst_id}`、`POST /market/sync/instruments` |
| `equity_asset` | `GET /market/equity-assets` |
| `candle` | `GET /market/candles`、`POST /market/backfill` |
| `equity_candle` | `GET /market/equity-candles` |
| `market_session` | `GET /market/sessions` |
| `data_source_sync` | `GET /market/sync-status` |
| `data_quality_issue` | `GET /market/quality-issues` |
| `market_snapshot` | `GET /market/snapshot` |
| `target_symbol` | `GET/POST /targets`、`PATCH/DELETE /targets/{id}` |
| `relation_snapshot` | `GET /targets/{id}/relations`、`POST /targets/{id}/relations/recompute` |
| `relation_edge` | 嵌套于 `relation_snapshot` 响应的 `edges[]` |
| `relative_strength_snapshot` | `GET /targets/{id}/relative-strength` |
| `opportunity_run` | `POST /opportunities/scan`、`GET /opportunities/runs`、`GET /opportunities/runs/{run_id}` |
| `opportunity` | `GET /opportunities`、`GET /opportunities/{id}` |
| `asset_cluster` | `GET /clusters` |
| `cluster_member` | 嵌套于 `asset_cluster` 响应的 `members[]` |
| `strategy` | `GET/POST /strategies`、`GET /strategies/{id}` |
| `strategy_leg` | 嵌套于 `strategy` 响应的 `legs[]` |
| `strategy_approval` | `POST /strategies/{id}/approve`、`POST /strategies/{id}/reject`、`GET /strategies/{id}/approvals` |
| `strategy_transition` | `GET /strategies/{id}/transitions` |
| `backtest_run` | `POST /backtests`、`GET /backtests`、`GET /backtests/{run_id}` |
| `backtest_metric` | `GET /backtests/{run_id}/metrics` |
| `backtest_equity_point` | `GET /backtests/{run_id}/equity` |
| `backtest_trade` | `GET /backtests/{run_id}/trades` |
| `job_run` | `GET /ops/job-runs`、`GET /ops/job-runs/{id}` |
| `audit_log` | `GET /ops/audit-log` |

## 3. 端点明细

### 3.1 健康

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 存活：`{"status":"ok","version":"0.1.0"}`，不查数据库 |
| GET | `/ready` | 就绪：数据库可连通则 200，否则 503 |

### 3.2 market

**`GET /api/v1/market/instruments`** — 查询参数 `asset_class`、`exchange`、`state`、`q`、`limit`、`cursor`。响应项含 `inst_id`、`inst_category`、`asset_class`、`exchange`、`ct_val`、`lot_sz`、`tick_sz`、`state`、`list_time`、`source_synced_at`（不得为空）。

**`GET /api/v1/market/instruments/{inst_id}`** — 单条，含 `raw` 之外的规整字段。

**`POST /api/v1/market/sync/instruments`** — 触发 `sync_instruments` 任务，`202`；`Idempotency-Key` 命中同一小时窗口时不重复执行。

**`GET /api/v1/market/candles`** — `inst_id`（必填）、`bar`（枚举 `1m|5m|15m|1h|4h|1d`）、`start`、`end`、`limit`、`cursor`。返回按 `open_time` 升序，含 `confirm` 标记；未收盘 bar 返回但 `confirm=false`。

**`POST /api/v1/market/backfill`** — body `{inst_id, bar, start, end}`，`202`。重复提交同一区间由 `ops.job_run` 幂等键吸收（`failed`/`partial` 允许同键重试），每次执行刷新 `data_source_sync` 账本。

**`GET /api/v1/market/sessions`** — `from`、`to`（默认最近 30 天），返回 `market_session` 行；`venue` 固定 `XNYS`。

**`GET /api/v1/market/sync-status`** — 返回 `items[]`：按 `source`/`dataset`/`scope` 聚合的最新同步状态（`status`、`window_start/end`、`rows_written`、`last_error`、`last_success_at`、`age_seconds`）与 `stale` 布尔（按数据集采集间隔 ×3 判定），并附 `stale` 计数、标的数与未解决质量问题数。

**`GET /api/v1/market/quality-issues`** — `status=open|resolved`（`open` 只返回 `resolved_at IS NULL`）、`kind`、`scope_id`；非法 `status` 返回 400。

**`GET /api/v1/market/coverage`** — `inst_id`、`bar`、`from`、`to`，返回逐日覆盖与缺口列表。

**`GET /api/v1/market/snapshot`** — `as_of`（或取最新），返回 `market_snapshot` 截面，供驾驶舱使用。

**`GET /api/v1/market/equity-assets`** / **`GET /api/v1/market/equity-candles`** — 真实行情侧，参数 `symbol`、`interval`、`start`、`end`。

### 3.3 targets 与关系

**`GET/POST /api/v1/targets`** — POST body `{symbol, exchange, display_name?, note?}`；`exchange` 必填且只接受 `XNAS` / `XNYS` / `NYSE_ARCA`（缺失或非法返回 `422 VALIDATION_ERROR`）。重复添加返回 `200` 与已存在记录，不产生副本；首次创建为 `201`。`GET` 默认只列 `enabled=true`，`enabled=false` 只看已软删除记录。DELETE 为软删除（`enabled=false`，行仍在），返回被更新的记录。

target 记录字段：`id`、`symbol`、`exchange`、`display_name`、`note`、`instrument_id`、`enabled`、`created_at`。`instrument_id` 由 `market.instrument.uly` 首段与 `symbol` 匹配得到，无匹配时为 `null`。

**`POST /api/v1/targets/{id}/relations/recompute`** — body `{window_bars, method, price_basis, as_of}`，`method` 为 `pearson|spearman`，`price_basis` 为 `okx_close|equity_close`，`as_of` 可省略（取最后一根 K 线时间）。首次提交返回 `202` 与 `{job_id, status, job_name, job_key}`，带 `Location: /api/v1/ops/job-runs/{id}`；相同参数再次提交返回 `200` 且 `status="skipped"`，不新增快照。`run_key` 只由口径身份（`target_id`、`as_of`、`window_bars`、`method`、`price_basis`）派生，`lag_max`/`stability_window`/`change_threshold` 来自配置并只写入 `params`，因此改配置后对同一 `as_of` 重算仍返回 `skipped`，不会撞上业务唯一键而失败。任务在 worker 中计算，产出 `relation_snapshot` + `relation_edge`。

**`GET /api/v1/targets/{id}/relations`** — 无 `as_of` 取最新快照；无快照时返回 `200` 且 `status="undefined"`、`snapshot=null`、`edges=[]`，`reason` 说明原因（不返回 500）。响应：

```json
{
  "status": "ok",
  "reason": null,
  "snapshot": {"id": 7, "target_id": 1, "as_of": "2026-11-06T00:00:00Z", "window_bars": 60, "method": "pearson", "price_basis": "okx_close", "lag_max": 5, "sample_size": 60, "run_key": "…", "computed_at": "2026-11-06T00:01:02Z", "params": {}},
  "edges": [{"counterparty_inst_id": "MSFT-USDT-SWAP", "counterparty": {"symbol": "MSFT", "exchange": "XNAS", "asset_class": "us_equity"}, "coefficient": "0.8123456789", "best_lag": 0, "p_value": "0.0000001", "stability": "0.9000000000", "rank": 1}],
  "significant_changes": [{"counterparty": "MSFT-USDT-SWAP", "kind": "changed", "previous": "0.5000000000", "current": "0.8123456789", "delta": "0.3123456789", "sign_flip": false, "significant": true}]
}
```

`status="undefined"` 表示样本不足或候选序列缺失，此时 `edges` 为空、`reason` 非空（例如 `MISSING_SOURCE: …`）。`significant_changes` 只含达到阈值（默认 `0.2`）或发生符号翻转的条目。

**`GET /api/v1/targets/{id}/relations/history`** — `limit`（默认 20），按 `as_of` 倒序返回快照序列，含每个快照的显著变化标记。

**`GET /api/v1/targets/{id}/relative-strength`** — `counterparty`（合约 `inst_id`，必填，不存在返回 `404 INSTRUMENT_NOT_FOUND`）、`lookback`（默认 60，范围 2–500）、`price_basis`。返回 `defined`、`reason`、`rs_ratio`、`rs_momentum`、`momentum_reason`、`target_return`、`counterparty_return`、`excess_return`、`trend`，以及供绘图的 `series[{ts, rs_ratio}]`。窗口不足时 `defined=false`、`reason` 非空，不返回空壳数值。

### 3.4 opportunities 与聚类

**`POST /api/v1/opportunities/scan`** — body `{as_of?, universe?, params?}`，`202`，返回 `job_id`；任务完成后可查 `run_id`。幂等键 = `(symbol 集合, window, as_of)`。

**`GET /api/v1/opportunities`** — `run_id`、`kind`、`direction`、`min_score`、`limit`、`cursor`；每项含 `reasons[]` 与 `evidence{}`（必须能解释"为什么是它"，不返回裸分数）。

**`GET /api/v1/opportunities/{id}`** — 单条，含成员与证据明细。

**`GET /api/v1/opportunities/runs`** / **`/runs/{run_id}`** — 批次状态、`universe_size`、计数与耗时。

**`GET /api/v1/clusters`** — `run_id`，返回 `asset_cluster` 及嵌套 `members[]`。

### 3.5 strategies 与审批

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/strategies` | `status`、`kind`、`limit`、`cursor` |
| POST | `/api/v1/strategies` | body `{kind, name, target_id?, templates[], params{}}` → 创建 `draft`；同参数返回已有 `strategy_key` 对应记录（`200`） |
| GET | `/api/v1/strategies/{id}` | 含 `legs[]`、当前 `status`、`content_hash` |
| POST | `/api/v1/strategies/{id}/submit` | `draft → pending_approval` |
| POST | `/api/v1/strategies/{id}/approve` | body `{reviewer, note?}`，`pending_approval → approved` |
| POST | `/api/v1/strategies/{id}/reject` | body `{reviewer, note}`，`pending_approval → rejected` |
| POST | `/api/v1/strategies/{id}/archive` | `approved/rejected → archived` |
| GET | `/api/v1/strategies/{id}/approvals` | `strategy_approval` 列表 |
| GET | `/api/v1/strategies/{id}/transitions` | `strategy_transition` 审计链 |

非法迁移返回 `409 strategy_illegal_transition`；`approved` 策略的任何内容字段修改返回 `409 strategy_readonly`（必须先 `archive` 再从模板新建，保证审批内容与回测内容一致）。

### 3.6 backtests

**`POST /api/v1/backtests`** — body：

```json
{
  "strategy_id": 12,
  "window": {"start": "2026-04-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
  "bar": "1h",
  "initial_capital": "100000",
  "cost_model": {"taker_fee_bps": "5", "maker_fee_bps": "2", "slippage_bps": "2", "funding": true}
}
```

`202` + `job_id`；`run_key` 由策略版本、窗口、bar、成本模型与参数哈希得到，同参数重复提交直接返回已有 `run_id`。

**`GET /api/v1/backtests/{run_id}`** — 状态、`strategy_version`、`started_at`、`finished_at`、`error`。
**`GET .../metrics`** — `backtest_metric` 列表（`name`、`value`、`unit`）。
**`GET .../equity`** — `backtest_equity_point` 序列（分页）。
**`GET .../trades`** — `backtest_trade` 列表，含成本拆解（`fees`/`funding`/`slippage`）。

### 3.7 ops

**`GET /api/v1/ops/job-runs`** — `job_name`、`status`、`from`、`to`，返回 `job_run` 列表。
**`GET /api/v1/ops/job-runs/{id}`** — 单条，含 `attempts`、`error`、`result`。
**`GET /api/v1/ops/audit-log`** — `resource`、`resource_id`、`from`、`to`。

## 4. 内部边界

- 服务进程之间**没有 HTTP 契约**。`api`、`worker`、`scheduler` 共享同一个 Python 包与同一套 `services`，通过 PostgreSQL 与 Redis 队列协作。
- `scheduler` 只能调用 `jobs` 的投递函数（写队列 + `job_run`），不得直接执行重计算。
- `worker` 任务的输入输出是 Python 对象，落库后对外表现为上表资源；不存在"内部 REST 接口"。
- 跨模块调用只允许：`opportunity → analysis`（纯函数）、`strategy.core`、`backtest.core`、`backtest → market`（读 K 线服务）。禁止横向调用其他模块的 service。
- 外部适配器只在 `adapters/` 内出现；`api` 层不得直接 import `httpx` 调外部接口。

## 5. 兼容与版本

- 破坏性变更升 `/api/v2`；P1 期间允许在 `/api/v1` 内新增可选字段与端点。
- 已发布字段不得改语义（例：`coefficient` 不得从 Pearson 改成 Spearman 却不改 `method`）。
- OpenAPI 文档由 FastAPI 自动生成，`/openapi.json` 仅内网暴露；本文与生成结果冲突时以本文为准并修正代码。
