# 数据模型（P1）

单一 PostgreSQL 16 实例，按限界上下文分 schema：`market`、`research`、`opportunity`、`strategy`、`backtest`、`ops`。跨 schema 只允许外键引用 `market.instrument` 与 `research.target_symbol`，其余禁止互相 JOIN 业务表。

约定先行，表结构后列。

## 1. 通用约定

### 1.1 时间

| 场景 | 存法 | 说明 |
| --- | --- | --- |
| 所有时间字段 | `TIMESTAMPTZ`，UTC | 库内不做本地时区存储，展示层转换 |
| K 线时间 | `open_time TIMESTAMPTZ`（开盘时刻） | 唯一键的一部分，不用 `close_time` 冗余 |
| API 传输 | ISO-8601 UTC，带 `Z` | 例 `2026-11-06T03:59:00Z` |
| 业务日 | `trading_date DATE`（仅 `market_session`） | 以交易所本地日为准，避免 UTC 跨日歧义 |

K 线锚定规则（实测，见 `docs/risk/external-dependencies.md`）：

- OKX `1D/1W/1M` 以 **UTC+8** 为日界（`1D` 的首根 `open_time` 为前一日 16:00Z）；`1Dutc` 以 UTC+0 为界。
- 库内只保留一种锚定：内部 bar 枚举 `1d` 固定映射 OKX `1D`（UTC+8 锚），历史数据不得混入 `1Dutc`。若后续需要使用 UTC 日界，追加独立 bar 枚举 `1d_utc` 并各自建唯一键，禁止在同一 `(instrument, bar)` 序列里混存。
- `8H` 周期在 OKX 不存在（`code 51000`）。资金费率是 8 小时结算，但**没有对应 K 线**，回测中按 8 小时时间窗自行切分。

### 1.2 精度

| 数据 | 类型 | 说明 |
| --- | --- | --- |
| 价格 | `NUMERIC(20,10)` | 覆盖 0.0000000001 ~ 1e10 |
| 数量 / 名义金额 / 权益 | `NUMERIC(24,10)` | 与 OKX `lotSz/ctVal` 对齐 |
| 比率 / 权重 / 相关系数 | `NUMERIC(12,10)` | 统计量为 float64 计算结果，入库前显式量化，保留 10 位 |
| 计数 | `BIGINT` / `INTEGER` | — |

规则：金额与价格在 Python 侧一律 `Decimal`，禁止经过 `float`；统计计算（相关性、聚类、指标）内部可用 `float64`，但输出必须显式 `quantize` 后入库，并在 API 中以**字符串**返回，避免前端 JSON 数字精度损失。

### 1.3 幂等与唯一键

| 类别 | 做法 |
| --- | --- |
| 行情入库 | 自然唯一键 + `INSERT ... ON CONFLICT DO UPDATE`（仅允许 `confirm: false → true` 与修订值更新） |
| 任务执行 | `ops.job_run (job_name, job_key)` 唯一；`job_key` = 任务参数规范化 JSON 的 sha256 |
| 派生结果 | `run_key` / `strategy_key` = 规范化参数 JSON 的 sha256，唯一约束即幂等键 |
| 写接口 | 客户端传 `Idempotency-Key`，落 `ops.audit_log.idempotency_key`，重复请求返回首次结果 |
| 采集问题 | `data_quality_issue` 按 `(dataset, scope_id, kind, window_start)` 去重，重复扫描只更新 `last_seen_at` |

## 2. market schema

### instrument（合约标的）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGSERIAL PK | |
| `inst_id` | TEXT | 例 `AAPL-USDT-SWAP` |
| `inst_family` / `uly` | TEXT | 例 `AAPL-USDT` |
| `inst_category` | SMALLINT | OKX 原始值：1 加密、3 股票、4 商品、5 外汇、6 债券 |
| `asset_class` | TEXT | 内部归类：`us_equity` / `foreign_equity` / `etf` / `index` / `private_company` / `commodity` / `crypto` |
| `exchange` | TEXT NULL | 映射到的真实交易所（`XNAS`/`XNYS`/`NYSE_ARCA` 等），无法映射则 NULL |
| `ct_val` / `ct_val_ccy` | NUMERIC / TEXT | 合约面值，`AAPL` 为 `1 AAPL` |
| `lot_sz` / `min_sz` / `tick_sz` | NUMERIC(24,10)/(20,10) | 下单与回测取整依据 |
| `lever` | NUMERIC(10,4) | 最大杠杆，P1 只作展示 |
| `state` | TEXT | `live` / `suspend` / `preopen` 等 |
| `rule_type` | TEXT | `normal` / `pre_market` 等，OKX 盘前规则 |
| `list_time` | TIMESTAMPTZ | 决定历史深度上限 |
| `source_synced_at` | TIMESTAMPTZ | 最近一次来源同步时间，API 必须返回 |
| `raw` | JSONB | 原始响应快照（审计用） |

唯一键：`UNIQUE (inst_id)`。幂等：按 `inst_id` upsert，内容未变只更新 `source_synced_at`。

### equity_asset（真实股票映射）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGSERIAL PK | |
| `symbol` | TEXT | 例 `AAPL` |
| `exchange` | TEXT | `XNAS` / `XNYS` / `NYSE_ARCA` / NULL |
| `currency` | TEXT | `USD` 等 |
| `timezone` | TEXT | 例 `America/New_York` |
| `source_symbol` | TEXT NULL | 外部源使用的代码（如 `AAPL`、`9984.T`） |
| `source_name` | TEXT NULL | 当前实际取数源，`yahoo` / `okx_index` / `none` |
| `mapping_status` | TEXT | `mapped` / `unmapped` / `private`（如 OPENAI、ANTHROPIC 无公开行情） |

唯一键：`UNIQUE (symbol, exchange)`。幂等：按 `(symbol, exchange)` upsert。

### candle（合约 K 线）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGSERIAL | 与 `open_time` 组成主键 |
| `instrument_id` | BIGINT FK | |
| `bar` | TEXT | 内部枚举：`1m` `5m` `15m` `1h` `4h` `1d` |
| `open_time` | TIMESTAMPTZ | 开盘时刻 |
| `open/high/low/close` | NUMERIC(20,10) | |
| `vol` / `vol_ccy` / `vol_ccy_quote` | NUMERIC(24,10) | OKX 三种成交量口径，全部保留 |
| `confirm` | BOOLEAN | OKX `confirm` 字段，`false` 为未收盘 |
| `source` | TEXT | `okx_rest` / `okx_history` |
| `ingested_at` | TIMESTAMPTZ | |

唯一键：`UNIQUE (instrument_id, bar, open_time)`。幂等：`ON CONFLICT DO UPDATE`，禁止删除重插。分区：`PARTITION BY RANGE (open_time)` 按月。

### equity_candle（真实股票 K 线）

字段同 `candle`，但 `equity_asset_id` 外键，另加 `session`（`PRE`/`REGULAR`/`POST`）与 `interval`（`1m`/`1d`）。唯一键：`UNIQUE (equity_asset_id, interval, ts)`。

### market_session（交易时段）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `venue` | TEXT | P1 只有 `XNYS`（含 NASDAQ 同日历） |
| `trading_date` | DATE | 交易所本地日 |
| `pre_start` / `pre_end` / `regular_start` / `regular_end` / `post_start` / `post_end` | TIMESTAMPTZ | 当日时段边界 |
| `is_half_day` / `is_holiday` | BOOLEAN | |
| `calendar_source` / `calendar_version` | TEXT | 例 `exchange_calendars` + 版本号 |

唯一键：`UNIQUE (venue, trading_date)`。幂等：按日 upsert。

### data_source_sync（采集账本）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` / `dataset` | TEXT | 例 `okx` / `candles_1m` |
| `scope` | TEXT | `instId` 或 `symbol` |
| `window_start` / `window_end` | TIMESTAMPTZ | 本次覆盖区间 |
| `status` | TEXT | `running` / `ok` / `partial` / `failed` |
| `attempts` / `rows_written` | INT / BIGINT | |
| `last_error` / `last_success_at` | TEXT / TIMESTAMPTZ | 陈旧检测依据 |
| `coverage` | JSONB | 逐日/逐小时覆盖摘要 |

唯一键：`UNIQUE (source, dataset, scope, window_start, window_end)`。

### data_quality_issue（数据质量）

`dataset`、`scope_id`、`kind`（`GAP`/`DUPLICATE`/`OUTLIER`/`STALE`/`UNCONFIRMED`/`MISSING_SOURCE`）、`severity`、`window_start`/`window_end`、`detail JSONB`、`detected_at`、`last_seen_at`、`resolved_at`。唯一键：`UNIQUE (dataset, scope_id, kind, window_start)`。

## 3. research schema

### target_symbol（目标股票）

`id`、`symbol`、`exchange`、`display_name`、`instrument_id`（对应合约，可空）、`enabled`、`note`、`created_at`。唯一键：`UNIQUE (symbol, exchange)`。重复添加返回已存在记录（200），不产生副本。

### relation_snapshot（关系快照头）

`id`、`target_id`、`as_of`、`window_bars`（如 60）、`method`（`pearson`/`spearman`）、`price_basis`（`okx_close`/`equity_close`）、`lag_max`、`sample_size`、`run_key`、`computed_at`、`params JSONB`。唯一键：`UNIQUE (run_key)`；业务唯一 `UNIQUE (target_id, as_of, window_bars, method, price_basis)`。

### relation_edge（关系边）

`id`、`snapshot_id`、`counterparty_id`、`coefficient NUMERIC(12,10)`、`best_lag INT`、`p_value`、`stability`（滚动窗口间符号一致率）、`rank`。唯一键：`UNIQUE (snapshot_id, counterparty_id, best_lag)`。

### relative_strength_snapshot（相对强弱）

`id`、`target_id`、`counterparty_id`、`as_of`、`lookback_bars`、`rs_ratio`、`rs_momentum`、`run_key`。唯一键：`UNIQUE (run_key)`。

### market_snapshot（全市场特征截面）

`id`、`run_id`（或 `as_of`）、`instrument_id`、`ret_1d`、`ret_5d`、`ret_20d`、`vol_20d`、`atr_14`、`volume_z`、`high_20d`、`low_20d`、`extras JSONB`。唯一键：`UNIQUE (as_of, instrument_id)`。

## 4. opportunity schema

### opportunity_run（扫描批次）

`id`、`run_key`、`as_of`、`universe_size`、`params JSONB`、`status`、`started_at`、`finished_at`、`error`、`counts JSONB`。唯一键：`UNIQUE (run_key)`；同一 `as_of` 重跑只更新自身。

### opportunity（机会）

`id`、`run_id`、`kind`（`directional`/`relative_value`）、`primary_instrument_id`、`direction`（`long`/`short`/`pair`）、`score NUMERIC(12,10)`、`horizon`（如 `1d`/`5d`）、`reasons JSONB`（人类可读理由数组）、`evidence JSONB`（相关系数、共振强度、偏离 z 值等原始量）、`dedupe_key`。唯一键：`UNIQUE (run_id, dedupe_key)`，`dedupe_key` 由成员集合与方向规范化后哈希得到。

### asset_cluster / cluster_member（聚类）

`asset_cluster`：`id`、`run_id`、`label`、`method`（`hierarchical`/`kmeans`）、`silhouette`、`size`、`centroid JSONB`；唯一键 `UNIQUE (run_id, label)`。
`cluster_member`：`cluster_id`、`instrument_id`、`distance`、`weight`；唯一键 `UNIQUE (cluster_id, instrument_id)`。

## 5. strategy schema

### strategy（策略）

`id`、`strategy_key`、`name`、`kind`（`directional`/`relative_value`）、`status`（`draft`/`pending_approval`/`approved`/`rejected`/`archived`）、`target_id`（可空）、`templates JSONB`、`params JSONB`、`content_hash`、`version`、`created_at`、`updated_at`、`approved_at`。唯一键：`UNIQUE (strategy_key)`；`UNIQUE (id, version)` 用于回测绑定版本。

### strategy_leg（策略腿）

`id`、`strategy_id`、`instrument_id`、`side`（`long`/`short`）、`target_weight NUMERIC(12,10)`、`rationale TEXT`、`rank`。唯一键：`UNIQUE (strategy_id, instrument_id)`（同一策略内不允许重复成员）。

### strategy_approval（审批）

`id`、`strategy_id`、`decision`（`approved`/`rejected`）、`content_hash`（审批时的内容指纹）、`reviewer`、`note`、`decided_at`。唯一键：`UNIQUE (strategy_id, content_hash, decision)`——内容变了必须重新审批，旧审批不生效。

### strategy_transition（状态迁移审计）

`id`、`strategy_id`、`from_status`、`to_status`、`at`、`actor`、`reason`、`request_id`。只追加，不更新；无业务唯一键，按 `(strategy_id, at)` 建索引。

## 6. backtest schema

### backtest_run

`id`、`run_key`、`strategy_id`、`strategy_version`、`window_start`、`window_end`、`bar`、`initial_capital NUMERIC(24,10)`、`cost_model JSONB`、`params JSONB`、`status`、`started_at`、`finished_at`、`error`。唯一键：`UNIQUE (run_key)`，其中 `run_key` 含策略版本与参数，参数相同则直接返回已有结果。

### backtest_metric

`id`、`run_id`、`name`（`total_return`/`annualized_return`/`max_drawdown`/`sharpe`/`sortino`/`win_rate`/`profit_loss_ratio`/`trade_count`/`turnover`/`cost_ratio`）、`value NUMERIC(24,10)`、`unit`。唯一键：`UNIQUE (run_id, name)`。

### backtest_equity_point / backtest_trade

`backtest_equity_point`：`run_id`、`ts`、`equity`、`cash`、`exposure`、`drawdown`；唯一键 `UNIQUE (run_id, ts)`。
`backtest_trade`：`run_id`、`instrument_id`、`side`、`entry_ts`、`exit_ts`、`entry_px`、`exit_px`、`qty`、`gross_pnl`、`fees`、`funding`、`slippage`、`net_pnl`、`bars_held`、`exit_reason`；唯一键 `UNIQUE (run_id, instrument_id, side, entry_ts)`。

## 7. ops schema

### job_run（任务账本）

`id`、`job_name`、`job_key`、`status`（`queued`/`running`/`ok`/`failed`/`skipped`）、`attempts`、`scheduled_at`、`started_at`、`finished_at`、`worker`、`error`、`payload_hash`、`result JSONB`。唯一键：`UNIQUE (job_name, job_key)`。

### audit_log（审计）

`id`、`request_id`、`actor`、`action`、`resource`、`resource_id`、`before JSONB`、`after JSONB`、`at`、`idempotency_key`。唯一键：`UNIQUE (idempotency_key)`（部分索引，仅非空时生效）。

## 8. 预留表（P1 不建，仅固定方向）

以下实体属 P2/P3，P1 不创建迁移，列出是为了让外键方向一次定对：

| 表 | 阶段 | 与 P1 的关系 |
| --- | --- | --- |
| `risk.risk_policy` / `risk.risk_event` | P2 | 引用 `strategy.strategy` 与 `market.instrument` |
| `execution.order` / `execution.fill` / `execution.position` | P3 | 引用 `strategy.strategy` 与 `market.instrument` |

## 9. 存储量与保留

按 227 个股票类合约、上市日起约 248 天估算：

| 周期 | 保留策略 | 行数量级 |
| --- | --- | --- |
| `1m` | 滚动 90 天 | ~29.4M |
| `5m` | 滚动 90 天 | ~5.9M |
| `15m` | 滚动 90 天 | ~2.0M |
| `1h` | 全量 | ~1.35M |
| `4h` | 全量 | ~0.34M |
| `1d` | 全量 | ~0.06M |

合计约 3900 万行，单机 PostgreSQL 可承载（分区 + `(instrument_id, bar, open_time)` 索引）。保留任务按月删除过期分区，删除前必须确认对应 `data_source_sync` 已记录覆盖区间。

## 10. 命名与枚举

- 表名小写复数、无前缀（schema 已表达上下文）；字段 `snake_case`。
- 时间字段后缀：`_at` 表示时刻，`_time` 表示 K 线/时段边界，`_date` 表示本地业务日。
- bar 内部枚举固定为 `1m/5m/15m/1h/4h/1d`，与 OKX 的映射只允许出现在 `adapters/okx` 内（`OKX_BAR = {"1h": "1H", "4h": "4H", "1d": "1D"}`）。
