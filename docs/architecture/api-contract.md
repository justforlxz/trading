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
| `risk_policy` | `GET /risk/policy`、`PUT /risk/policy` |
| `risk_event` | `GET /risk/events` |
| `execution.order` | `POST /execution/orders`（真实）、`POST /execution/paper/orders`（模拟）、`GET /execution/orders`、`GET /execution/orders/{id}`、`POST /execution/orders/{id}/sync`、`POST /execution/orders/{id}/cancel` |
| `execution.fill` | 嵌套于订单响应的 `fills[]` |
| `execution.position` | `GET /execution/positions`、`GET /execution/account` |
| `execution.reconcile_diff` | `POST /execution/reconcile`、`GET /execution/reconcile/diffs`、`POST /execution/reconcile/diffs/{id}/resolve` |
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
| PATCH | `/api/v1/strategies/{id}` | body `{name?, params?, legs?}`；仅 `draft` / `rejected` 可编辑，编辑后重算 `content_hash` 且 `version + 1`；其余状态返回 `409 strategy_readonly` |
| POST | `/api/v1/strategies/{id}/submit` | `draft → pending_approval` |
| POST | `/api/v1/strategies/{id}/approve` | body `{reviewer, note?}`，`pending_approval → approved` |
| POST | `/api/v1/strategies/{id}/reject` | body `{reviewer, note}`，`pending_approval → rejected` |
| POST | `/api/v1/strategies/{id}/archive` | `approved/rejected → archived` |
| GET | `/api/v1/strategies/{id}/approvals` | `strategy_approval` 列表 |
| GET | `/api/v1/strategies/{id}/transitions` | `strategy_transition` 审计链 |

非法迁移返回 `409 strategy_illegal_transition`；`approved` 策略的任何内容字段修改返回 `409 strategy_readonly`（必须先 `archive` 再从模板新建，保证审批内容与回测内容一致）。

策略域错误码：`404 TARGET_NOT_FOUND` / `OPPORTUNITY_NOT_FOUND` / `STRATEGY_NOT_FOUND`；`409 strategy_illegal_transition` / `strategy_readonly` / `strategy_key_conflict`；`422 strategy_unknown_template` / `strategy_unevidenced_leg` / `strategy_no_source_data` / `strategy_source_required` / `strategy_invalid_param` / `strategy_reserved_param` / `strategy_instrument_not_found` / `strategy_position_limit` / `strategy_gross_exposure_exceeded` / `strategy_net_exposure_exceeded` / `strategy_min_legs` / `strategy_max_legs` / `strategy_duplicate_leg` / `strategy_side_weight_mismatch`。全部使用统一错误信封。

### 3.6 backtests

回测只接受 `status=approved` 的策略，只读 `market.candle` 中 `confirm=true` 的 K 线；
不写任何交易域数据，不接私有接口。资金费没有采集来源，只能按常数假设并显式标注。
`params` 中固定写入 `data_source=okx_usdt_perp_candle`、`price_basis=okx_close`、
`funding_assumption=constant`，供报告页与审计对齐口径。

**`POST /api/v1/backtests`** — body：

```json
{
  "strategy_id": 12,
  "window": {"start": "2026-04-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
  "windows": [
    {"name": "w1", "start": "2026-04-01T00:00:00Z", "end": "2026-07-01T00:00:00Z",
     "role": "train"},
    {"name": "w2", "start": "2026-07-01T00:00:00Z", "end": "2026-11-01T00:00:00Z",
     "role": "test"}
  ],
  "bar": "1h",
  "initial_capital": "100000",
  "cost_model": {
    "taker_fee_bps": "5", "maker_fee_bps": "2", "slippage_bps": "2",
    "funding_bps_per_period": "1", "funding": true, "fee_role": "taker"
  },
  "criteria": {"thresholds": [{"name": "sharpe", "op": ">=", "value": "1"}]},
  "annualization_factor": "252",
  "risk_free_rate": "0",
  "rebalance": "none"
}
```

`windows` 可省略：主窗口出整段汇总指标，每个分段再出 `指标@窗口名`；
walk-forward 要求训练段严格早于测试段且互不重叠，分段必须落在主窗口内。
`202` + `run_id` / `job_id`；`run_key` 由策略版本、窗口、bar、成本模型与参数哈希得到，
同参数重复提交返回已有运行（`200`，`created=false`），不重复排队。

**错误码**：非 `approved` 策略 `409 strategy_not_approved`；窗口内某条腿没有
`confirm=true` 的 K 线 `422 insufficient_data`（`details.gaps` 列明标的与窗口）；
非法 bar / 空窗口 / 窗口过长 `422 backtest_invalid_bar` / `backtest_window_invalid` /
`backtest_window_too_long`。

**`GET /api/v1/backtests/{run_id}`** — 状态、`strategy_version`、`started_at`、
`finished_at`、`error`，以及 `params.criteria`（阈值、逐条 `actual`/`passed`、
整体 `passed`、是否 `default`）和 `funding_assumption`。
**`GET .../metrics`** — `backtest_metric` 列表（`name`、`value`、`unit`）。
**`GET .../equity`** — `backtest_equity_point` 序列（`ts`、`equity`、`cash`、
`exposure`、`drawdown`，按 `cursor` 分页）。
**`GET .../trades`** — `backtest_trade` 列表，含成本拆解
（`fees`/`funding`/`slippage`）与 `net_pnl`，按 `cursor` 分页。

### 3.7 risk

风控只读 `strategy`、`market`、`backtest` 数据，不写交易域，不接私有接口，不下单。
所有判决由 `app.risk.core` 纯函数计算，服务层只做查询、编排与事件落库。
**fail-closed**：K 线缺失、依赖不可用、计算异常一律返回拒绝放行，不抛 500。

**`GET /api/v1/risk/policy`** — 查询参数 `strategy_id`（省略即全局）。返回当前最高版本阈值：
`{scope, strategy_id, version, thresholds{...}, updated_at, updated_by, note}`。
阈值以字符串返回（`NUMERIC` 精度，避免 float 误差）。不存在任何版本时按配置默认值自动创建 `version=1`（幂等）。

**`PUT /api/v1/risk/policy`** — body：

```json
{
  "expected_version": 1,
  "updated_by": "risk-admin",
  "note": "收紧集中度",
  "strategy_id": 12,
  "thresholds": {
    "max_order_notional": "20000",
    "max_leg_weight": "0.6",
    "max_leverage": "1.0",
    "max_gross_exposure": "1.0",
    "max_net_exposure": "1.0",
    "max_instrument_weight": "0.6",
    "max_concentration": "0.5",
    "drawdown_warn": "0.05",
    "drawdown_reduce": "0.10",
    "drawdown_close": "0.20",
    "funding_rate_threshold": "0.0005",
    "min_depth_notional": "20000"
  }
}
```

写入新版本行（`version = expected_version + 1`）并返回新策略。`expected_version` 与当前版本不符返回
`409 risk_policy_stale`（`details` 含 `current_version`、`expected_version`）；阈值非法（非正、回撤未满足
`0 < warn < reduce < close`、字段缺失）返回 `422 risk_invalid_threshold`。

**`GET /api/v1/risk/status`** — 查询参数 `strategy_id`。只读、不落事件、不查 K 线。
`strategy_id` 省略时按全部 `approved` 策略汇总全局组合。响应：

```json
{
  "scope": "strategy",
  "strategy_id": 12,
  "policy_version": 2,
  "allowed": false,
  "reason": "limit_breach",
  "limits": {"max_gross_exposure": "0.5", "...": "..."},
  "capital": "100000",
  "gross_exposure": "140000",
  "net_exposure": "40000",
  "leverage": "1.4",
  "concentration": "0.9",
  "long_exposure": "90000",
  "short_exposure": "50000",
  "long_short_conflicts": [7],
  "duplicates": [{"instrument_id": 7, "side": "long", "strategy_ids": [12, 13]}],
  "breaches": [{"code": "gross_exposure_exceeded", "field": "gross_exposure",
                "observed": "1.4", "threshold": "0.5"}]
}
```

`reason` 取值：`null`（放行）、`limit_breach`、`strategy_not_approved`、`risk_empty_portfolio`、
`risk_evaluation_failed`。策略不存在返回 `404 not_found`。

**`GET /api/v1/risk/events`** — `kind`（`limit_breach|drawdown|funding|liquidity`）、`severity`
（`tier1|tier2|tier3`）、`strategy_id`、`since`（ISO-8601）、`limit`（默认 50，上限 200）、`cursor`。
按 `id` 倒序返回 `{items[], next_cursor}`。事件项含 `kind`、`severity`、`action`、`strategy_id`、
`instrument_id`、`policy_version`、`observed_value`、`threshold`、`payload`、`evaluation_key`、
`created_at`、`resolved_at`。同一评估键下重复评估不会产生重复行。`cursor` 非整数返回 `400 invalid_request`。

**`GET /api/v1/risk/funding`** — `strategy_id` 或 `inst_ids`（逗号分隔）。读取 OKX 公开
`GET /api/v5/public/funding-rate` 与 `GET /api/v5/market/books`（免鉴权，不涉及账户）。
返回 `{items[], breaches[], missing[]}`：`items` 为资金费率与盘口观测（数值字符串），`breaches` 为超阈值/深度不足
信号（`kind=funding|liquidity`），`missing` 为缺失观测的 `inst_id`。任一标的缺失即 `503
risk_market_data_unavailable`（fail-closed），`details.missing` 列出缺失标的；上游不可用返回 `503 dependency_unavailable`。

**`POST /api/v1/risk/evaluate`** — body `{strategy_id, as_of?, evaluation_key?}`。按 `ops.job_run` 幂等键投递
`risk_evaluate` 任务，`202` 返回 `{run_id, job_id, status, run_key, created, dispatched}`；
同参数重复提交复用同一 `run_id` 并返回 `200`、`created=false`、`dispatched=false`。
评估键缺省取 `as_of` 的日期（`YYYY-MM-DD`），决定事件的去重粒度。任务完成后超限与回撤各自落一条
`risk_event`（`kind=limit_breach` / `drawdown`）。

### 3.8 ops

**`GET /api/v1/ops/job-runs`** — `job_name`、`status`、`from`、`to`，返回 `job_run` 列表。
**`GET /api/v1/ops/job-runs/{id}`** — 单条，含 `attempts`、`error`、`result`。
**`GET /api/v1/ops/audit-log`** — `resource`、`resource_id`、`from`、`to`。

### 3.9 execution

执行域只读 `strategy` / `risk` / `market` 数据，统一下单入口是
`app.execution.service.submit_order`；paper 与 real 共用同一套订单生命周期与状态机，
只有交易源（`PrivateTradingSource`）不同。数值一律字符串，错误沿用 §1.1 信封。

**`GET /api/v1/execution/mode`** — 返回
`{mode, real_trading_enabled, credentials_configured, real_strategy_ids[], paper_fill_chunks[], stop_loss_ratio, reason}`。
`mode` 为 `paper` 或 `real`；`REAL_TRADING_ENABLED` 缺省 `false` 时固定 `paper` 且 `reason=real_trading_disabled`。

**`POST /api/v1/execution/orders`** — **真实**下单。`REAL_TRADING_ENABLED` 未显式打开时始终返回
`403 real_trading_disabled`（门禁先于请求体校验执行，因此空请求体也返回 403）。
开关打开后仍需：凭据齐全（`403 execution_credentials_missing`）、策略在
`EXECUTION_REAL_STRATEGY_IDS` 中（`403 execution_strategy_not_authorized`）、无未处理对账差异
（`403 execution_reconcile_pending`）。body：

```json
{
  "strategy_id": 12,
  "inst_id": "BTC-USDT-SWAP",
  "side": "buy",
  "position_side": "long",
  "quantity": "0.01",
  "order_type": "market",
  "price": null,
  "reduce_only": false,
  "intent": "entry",
  "client_order_id": "t-0001"
}
```

`201` 返回订单视图与 `Location: /api/v1/execution/orders/{id}`；同 `client_order_id` 重复提交返回 `200`
与同一订单，且不再次触达交易所。若 `client_order_id` 相同但请求载荷（策略/标的/方向/数量/价格/意图）
不同，返回 `409 execution_idempotency_conflict`，绝不静默返回旧单；并发同 key 由数据库唯一约束兜底，
冲突后回查既有单并按幂等语义返回。其余错误：`409 execution_strategy_not_approved`、
`409 execution_risk_rejected`（details 带 `reason` / `breaches`）、
`409 execution_position_inconsistent`（`reduce_only` 平仓数量超过该策略持仓，details 带
`requested` / `available`，在落库与触达交易所之前拒绝）、`502 execution_upstream_rejected`、
`503 execution_upstream_unavailable`（状态未知，留给恢复流程判定）。

**`POST /api/v1/execution/paper/orders`** — 模拟下单，任何模式下可用，绝不构造交易所客户端。
请求与响应同上。paper 撮合按 `EXECUTION_PAPER_FILL_CHUNKS`（默认 `0.5,0.5`）分段成交，
因此市价单首次返回 `state=partial`，再调用一次 `POST /execution/orders/{id}/sync` 后变 `filled`。

**`GET /api/v1/execution/orders`** — 查询参数 `strategy_id`、`state`、`mode`、`limit`（≤200）、`cursor`；
返回 `{items[], next_cursor}`。
**`GET /api/v1/execution/orders/{id}`** — 订单视图 + `fills[]`。
**`POST /api/v1/execution/orders/{id}/sync`** — 拉取交易所订单与成交并推进状态机（幂等，重复同步不重复计仓）。
**`POST /api/v1/execution/orders/{id}/cancel`** — 撤单；终态订单幂等返回当前视图。

**`GET /api/v1/execution/positions`** — `strategy_id` 可选。返回
`{items[], totals{realized_pnl, unrealized_pnl, total_pnl, gross_notional, net_notional, positions}}`；
`item` 含 `strategy_id`、`instrument_id`、`inst_id`、`position_side`、`quantity`、`average_price`、
`realized_pnl`、`mark_price`、`unrealized_pnl`、`unrealized_ratio`、`notional`。
**`GET /api/v1/execution/account`** — `{mode, totals{...}, open_diffs}`。

**`POST /api/v1/execution/reconcile`** — 本地虚拟持仓与未完成订单对交易所事实比对，返回
`{checked_positions, checked_orders, diffs, open_diffs}`；只记录差异，不改本地数据。
**`GET /api/v1/execution/reconcile/diffs`** — `status=open|resolved`、`limit`、`cursor`。
**`POST /api/v1/execution/reconcile/diffs/{id}/resolve`** — body `{resolved_by, note?}`；结案后不再阻断下单。

**`POST /api/v1/execution/recovery`** — 恢复未完成订单：paper 先按持久化成交重建撮合状态；交易所仍有该单则
接管并补记成交，查无此单则 `pending → rejected`、其余 `→ canceled`，绝不重发；随后执行一次对账。
**`POST /api/v1/execution/stops/evaluate`** — body `{threshold_ratio?, persist?}`。单腿浮亏占持仓均价比例达到
阈值时产生 `reduce_only` 平仓单并写 `risk_event(kind=stop_trigger, action=close)`，不经过策略审批；
已有未完成止损单时不重复下单。

### 3.10 MCP

把 P1–P3 的只读能力与受控操作以 **Model Context Protocol**（JSON-RPC 2.0 over HTTP）暴露给外部 Agent。
服务本身**不含 LLM**、不做自然语言理解、不参与交易决策（决策依据：ADR-0007）。完整说明见 `docs/mcp.md`。

**`POST /mcp`** — Streamable HTTP，支持 JSON 与 SSE 两种响应形态（`Accept: text/event-stream` 返回
`event: message` 帧）；`trading-mcp`（`python -m app.mcp.stdio`）只是把 stdio 转发到该端点。

| 项 | 契约 |
| --- | --- |
| 鉴权 | `Authorization: Bearer <token>`；服务端只存 `sha256(token)`，明文仅在创建时返回一次 |
| 鉴权失败 | **HTTP 401** + §1.1 统一错误信封（不是 JSON-RPC error），`code=mcp_unauthorized`（缺令牌 / 未知 / 已吊销同码） |
| 方法 | `initialize`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`；未知方法 `-32601`，参数错误 `-32602`，非法 JSON `-32700`（HTTP 400） |
| 批量 / 通知 | 数组一次返回响应数组；全为 notification 时 HTTP 202 空体，只留审计不执行业务 |
| scope 不足 | **HTTP 403** + JSON-RPC error `-32003`，`data.code=mcp_forbidden`；只写一条 `mcp.mcp_call_log` 审计行，不产生任何业务写入 |
| 工具失败 | HTTP 200，`result.isError=true`，`content[0].text` 为 `{"error":{code,message,details}}` |
| 审计 | 每次调用写 `mcp.mcp_call_log`（client_id、method、tool、scope 判定、结果、时间） |

工具集（`backend/app/mcp/tools.py`，共 26 个）：

- **只读 18 个**（scope `read`）：`market_status`、`list_instruments`、`get_candles`、`data_coverage`、
  `list_targets`、`get_target`、`get_relations`、`get_relative_strength`、`list_opportunities`、
  `get_opportunity`、`list_strategies`、`get_strategy`、`get_backtest`、`risk_status`、`list_risk_events`、
  `list_positions`、`list_orders`、`virtual_positions`。返回值与对应 REST GET 语义一致。
- **受控操作 8 个**（scope `operate`）：`trigger_scan`、`create_strategy_draft`、`update_strategy_draft`、
  `submit_strategy_for_approval`、`run_backtest`、`pause_strategy`、`resume_strategy`、
  `execute_strategy_action`。全部复用既有 REST 的同一套服务与门禁：策略仍需人工审批、回测仍需已审批策略、
  真实下单仍受 `REAL_TRADING_ENABLED` 与策略授权约束，MCP 不提供绕过风控与审批的通道。

**`POST /api/v1/mcp/clients`** — body `{name, scopes[]}`，`scopes ⊆ {"read","operate"}`；
返回 `201 {client:{id,name,scopes,created_at,revoked_at}, token}`，`token` 只在此响应出现一次。
**`GET /api/v1/mcp/clients`** — `{items:[...]}`，不回显 token。
**`DELETE /api/v1/mcp/clients/{id}`** — 吊销，返回 200 与 `revoked:true`；吊销后同一 token 立即 401。

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
