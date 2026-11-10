# 数据模型（P1）

单一 PostgreSQL 16 实例，按限界上下文分 schema：`market`、`research`、`opportunity`、`strategy`、`backtest`、`ops`、`risk`、`execution`、`mcp`。跨 schema 外键白名单固定为三张表：`market.instrument`、`research.target_symbol`、`strategy.strategy`（与 `adr/0002-single-postgres-schema.md` 一致），其余禁止互相 JOIN 业务表。

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
| `asset_class` | TEXT | 内部归类：`us_equity` / `foreign_equity` / `etf` / `index` / `private_company` / `commodity` / `crypto` / `unclassified` |
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

唯一键：`UNIQUE NULLS NOT DISTINCT (symbol, exchange)`。**必须**使用 PG15+ 的 `NULLS NOT DISTINCT`（本项目 PG16）：`exchange` 允许为 NULL（私有/未上市标的），而默认唯一约束把 NULL 视为互不相等，会导致重复同步时 `ON CONFLICT (symbol, exchange)` 无法命中既有行、每次同步新增一条重复记录。幂等：`INSERT ... ON CONFLICT (symbol, exchange) DO UPDATE`。

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

唯一键：`UNIQUE (instrument_id, bar, open_time)`。幂等：`ON CONFLICT DO UPDATE`，禁止删除重插。

**与初版设计的偏差（S3 实施记录）**：初版写「`PARTITION BY RANGE (open_time)` 按月」。但 `candle` 同时承载 1m 到 1d 六种周期，按 `open_time` 单键分区时同一分区内混有短周期与长周期数据，无法只清短周期；而保留策略要求 1m/5m/15m 滚动 90 天、1h 及以上全量。因此改为**不分区**，保留任务按 `bar` 行级批量 `DELETE`（见 §9 与 `docs/market-data.md`）。改变保留策略或数据量级需要重新评估分区方案。

### equity_candle（真实股票 K 线）

字段同 `candle`，但 `equity_asset_id` 外键，另加 `session`（`PRE`/`REGULAR`/`POST`）与 `interval`（`1m`/`1d`）。唯一键：`UNIQUE (equity_asset_id, interval, ts)`。

### basis_snapshot（合约与真实股价基差）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGSERIAL PK | |
| `instrument_id` | BIGINT FK → `market.instrument.id` | 合约标的 |
| `symbol` | TEXT | 冗余股票代码，便于按 symbol 查询 |
| `ts` | TIMESTAMPTZ | 真实行情时间戳（`EquityQuote.ts`） |
| `okx_price` / `equity_price` | NUMERIC(20,10) | 同一时刻的合约价与真实价 |
| `basis_bps` | NUMERIC(12,4) | `(okx / equity - 1) * 10000`，基点 |
| `source` | TEXT | 真实行情来源（`yahoo` / `none`） |
| `created_at` | TIMESTAMPTZ | |

唯一键：`UNIQUE (instrument_id, ts)`。幂等：`ON CONFLICT DO UPDATE`。基差绝对值超过 `basis_alert_bps`（默认 500bps）时另写一条 `data_quality_issue(kind=OUTLIER, dataset=market.basis)`。

### market_session（交易时段）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `venue` | TEXT | P1 只有 `XNYS`（含 NASDAQ 同日历） |
| `trading_date` | DATE | 交易所本地日 |
| `pre_start` / `pre_end` / `regular_start` / `regular_end` / `post_start` / `post_end` | TIMESTAMPTZ | 当日时段边界 |
| `is_half_day` / `is_holiday` | BOOLEAN | |
| `calendar_source` / `calendar_version` | TEXT | 本实现为内置规则 `builtin:us-equity-v1` + `v1`（`exchange_calendars` 只作测试 oracle，不进运行时） |

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

`id`、`symbol`、`exchange`（**NOT NULL**，创建时必填，取值 `XNAS`/`XNYS`/`NYSE_ARCA`；目标是用户显式添加的股票，不允许未知交易所）、`display_name`、`instrument_id`（对应合约，可空）、`enabled`、`note`、`created_at`。唯一键：`UNIQUE (symbol, exchange)`（两列均非空，无需 `NULLS NOT DISTINCT`）。重复添加返回已存在记录（200），不产生副本。

### relation_snapshot（关系快照头）

`id`、`target_id`、`as_of`、`window_bars`（如 60）、`method`（`pearson`/`spearman`）、`price_basis`（`okx_close`/`equity_close`）、`lag_max`、`sample_size`、`run_key`、`computed_at`、`params JSONB`。唯一键：`UNIQUE (run_key)`；业务唯一 `UNIQUE (target_id, as_of, window_bars, method, price_basis)`。

### relation_edge（关系边）

`id`、`snapshot_id`、`counterparty_id`、`coefficient NUMERIC(12,10)`、`best_lag INT`、`p_value`、`stability`（滚动窗口间符号一致率）、`rank`。唯一键：`UNIQUE (snapshot_id, counterparty_id, best_lag)`。

### relative_strength_snapshot（相对强弱）

`id`、`target_id`、`counterparty_id`、`as_of`、`lookback_bars`、`rs_ratio`、`rs_momentum`、`run_key`。唯一键：`UNIQUE (run_key)`。

### market_snapshot（全市场特征截面）

`id`、`as_of`（截面时刻，唯一键的一部分）、`run_id`（可空，产生该截面的扫描批次，仅用于溯源，不参与唯一性）、`instrument_id`、`ret_1d`、`ret_5d`、`ret_20d`、`vol_20d`、`atr_14`、`volume_z`、`high_20d`、`low_20d`、`extras JSONB`。唯一键：`UNIQUE (as_of, instrument_id)`。

### 3.1 实施口径（S4）

上述四表由 `0003_research_schema` 迁移建立，计算口径与文档描述的对应关系如下。

- **`relation_edge.coefficient`**：`best_lag` 处的皮尔逊或斯皮尔曼相关系数，落在 `NUMERIC(12,10)`；`best_lag` 为正表示对手方领先目标若干根 K 线（`source` 方向由该符号决定）。样本数不足、任一侧为常数序列或无法对齐时该边不写入。
- **`relation_edge.p_value`**：`|r|=1` 时为 `0`，否则按 Student-t 分布（自由度 `sample_size-2`）计算的双侧 p 值，`NUMERIC(12,10)`；`sample_size<3` 为 `NULL`。
- **`relation_edge.stability`**：全样本相关系数符号与滚动窗口（默认 20 根）相关系数符号的一致率，范围 `[0,1]`；不存在有效滚动窗口时为 `NULL`，不用 `0` 冒充。
- **`relation_snapshot.run_key` 的口径**：只由口径身份（`target_id`、`as_of`、`window_bars`、`method`、`price_basis`）哈希得到，与业务唯一键 `(target_id, as_of, window_bars, method, price_basis)` 表达同一组语义；`lag_max`/`stability_window`/`change_threshold` 只写进 `params`，不进键。两者一致才不会出现「`run_key` 命中新值、业务唯一键命中旧行」的双约束冲突。因此改配置后对同一 `as_of` 重算得到 `skipped`，显著变化阈值本来就在读取时按当前配置计算，无需重算快照。
- **候选集排除目标自身**：按 `instrument_id` 与 `symbol`（`uly` 首段）双重排除。`instrument_id` 允许为空（建目标时行情尚未同步），只按 id 排除会让目标以候选身份重新进入，产生 `r=1.0` 的自环边。
- **`relative_strength_snapshot.run_key` 的口径**：`target_id`、`counterparty_id`、`as_of`、`lookback_bars`、`price_basis`、`momentum_bars` 的哈希；缺少口径或动量窗口会让 `okx_close` 与 `equity_close` 撞同一键并被静默丢弃。
- **`relation_snapshot.params`**：记录本次计算的 `lag_max`、`stability_window`、`change_threshold`、候选口径（`CORRELATION_ASSET_CLASSES`）以及被跳过的候选数与原因，便于解释为什么某些股票没有出现在边里。
- **`relation_snapshot` 的落库时机**：只有目标序列可用时才写快照；目标行情缺失（例如 `equity_close` 无真实行情）时任务以 `partial` 结束并写 `MISSING_SOURCE`，不写空壳快照。快照存在但没有任何候选边时，`params["reason"]` 记录原因，读取接口返回 `status="undefined"`。
- **`relative_strength_snapshot` 的落库口径**：`rs_ratio` 为窗口起点归一化为 1 的比值序列末值，`rs_momentum` 为当前 `rs_ratio` 相对 `momentum_bars` 前的相对变化（默认 `lookback/5`，至少 1 根）。读取接口计算成功后按 `run_key` 幂等写入（`ON CONFLICT DO NOTHING`），因此同一组参数重复查询不产生新行；`defined=false` 时只返回原因，不落库。


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

`id`、`strategy_key`、`name`、`kind`（`directional`/`relative_value`）、`status`（`draft`/`pending_approval`/`approved`/`rejected`/`archived`）、`target_id`（可空）、`templates JSONB`、`params JSONB`、`content_hash`、`version`、`created_at`、`updated_at`、`approved_at`、`paused_at`（可空，`0009_mcp_schema` 新增：策略被暂停时记录时刻；暂停中 `execute_strategy_action` 拒绝执行并返回 `strategy_paused`，策略状态本身不变，`resume_strategy` 清空该字段）。唯一键：`UNIQUE (strategy_key)`；`UNIQUE (id, version)` 用于回测绑定版本。

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

`id`、`job_name`、`job_key`、`status`（`queued`/`running`/`ok`/`partial`/`failed`/`skipped`）、`attempts`、`scheduled_at`、`started_at`、`finished_at`、`worker`、`error`、`payload_hash`、`result JSONB`。唯一键：`UNIQUE (job_name, job_key)`。`partial` 表示任务已完成但有标的或周期采集失败，缺口已写 `data_quality_issue`。

### audit_log（审计）

`id`、`request_id`、`actor`、`action`、`resource`、`resource_id`、`before JSONB`、`after JSONB`、`at`、`idempotency_key`。唯一键：`UNIQUE (idempotency_key)`（部分索引，仅非空时生效）。

## 8. risk schema（P2 已落地）

风控只读引用 `strategy.strategy` 与 `market.instrument`，不反向被业务模块引用。金额列用 `NUMERIC(24,10)`，比例列用 `NUMERIC(12,10)`，禁止 float。

### risk_policy（阈值策略，版本化）

`id`、`scope`（`global`/`strategy`）、`strategy_id`（`scope=strategy` 时非空，引用 `strategy.strategy.id`，级联删除）、`version`、阈值列：

| 列 | 类型 | 含义 |
| --- | --- | --- |
| `max_order_notional` | `NUMERIC(24,10)` | 单笔名义金额上限 |
| `max_leg_weight` | `NUMERIC(12,10)` | 单腿权重上限 |
| `max_leverage` | `NUMERIC(12,10)` | 杠杆上限 |
| `max_gross_exposure` | `NUMERIC(12,10)` | 总敞口 / 资本上限 |
| `max_net_exposure` | `NUMERIC(12,10)` | 净敞口 / 资本上限 |
| `max_instrument_weight` | `NUMERIC(12,10)` | 单标的权重上限 |
| `max_concentration` | `NUMERIC(12,10)` | 集中度上限 |
| `drawdown_warn` / `drawdown_reduce` / `drawdown_close` | `NUMERIC(12,10)` | 回撤三级阈值 |
| `funding_rate_threshold` | `NUMERIC(12,10)` | 资金费率绝对值阈值 |
| `min_depth_notional` | `NUMERIC(24,10)` | 盘口最小深度 |

另有 `note`、`updated_by`（记录调用来源与备注）、`created_at`、`updated_at`。

唯一键：`UNIQUE (scope, strategy_id, version) NULLS NOT DISTINCT` —— `global` 作用域的 `strategy_id` 为 NULL，`NULLS NOT DISTINCT` 保证同一作用域同一版本只能存在一行。版本单调递增，更新阈值即插入新版本行，旧版本保留以便事件回溯。

### risk_event（风险事件）

`id`、`kind`（`limit_breach`/`drawdown`/`funding`/`liquidity`）、`severity`（`tier1`/`tier2`/`tier3`）、`action`（`none`/`warn`/`reduce`/`close`）、`strategy_id`（可空，引用 `strategy.strategy.id`，置空删除）、`instrument_id`（可空，引用 `market.instrument.id`，置空删除）、`policy_version`、`observed_value`、`threshold`、`payload JSONB`、`evaluation_key`、`created_at`、`resolved_at`。

唯一键：`UNIQUE (kind, strategy_id, instrument_id, policy_version, evaluation_key) NULLS NOT DISTINCT` —— 同一评估键下重复评估不会产生重复事件行，API 只体现去重语义（不计数）。`created_at` 上建有索引，用于面板按时间倒序分页。

## 9. execution schema（P3 交易执行）

订单、成交、策略级虚拟持仓与对账差异。跨 schema 外键仍只允许 `strategy.strategy.id` 与
`market.instrument.id`；`risk.risk_event.id` 只作为止损单的可选回溯引用。
所有金额列使用 `NUMERIC(24,10)`。

### order（订单）

`id`、`client_order_id`（OKX `clOrdId`，唯一）、`exchange_order_id`（可空）、`mode`（`paper`/`real`）、
`strategy_id`（可空，引用 `strategy.strategy.id`，置空删除）、`instrument_id`（引用 `market.instrument.id`，级联删除）、
`inst_id`（冗余存储，交易所调用需要）、`side`（`buy`/`sell`）、`position_side`（`long`/`short`）、
`order_type`（`market`/`limit`）、`quantity`、`price`（可空）、`reduce_only`、`intent`（`entry`/`exit`/`stop`）、
`state`、`filled_quantity`、`average_price`（可空）、`fee`、`reject_reason`（可空）、
`risk_event_id`（可空，引用 `risk.risk_event.id`，置空删除）、`created_at`、`updated_at`、
`submitted_at`（可空）、`closed_at`（可空）。

唯一键：`UNIQUE (client_order_id)` —— 幂等下单的唯一闸门：同 `clOrdId` 重复提交返回同一订单，不再触达交易所。
状态枚举：`pending → submitted → partial → filled`，以及终态 `canceled` / `rejected`；合法迁移由
`app/execution/core/orders.ALLOWED_TRANSITIONS` 唯一定义，数据库 `CHECK` 只兜底取值范围。
约束：`quantity > 0`、`0 <= filled_quantity <= quantity`。

### fill（成交）

`id`、`order_id`（引用 `execution."order".id`，级联删除）、`fill_id`（交易所成交 id 或本地成交 id）、
`strategy_id`（可空）、`instrument_id`、`inst_id`、`side`、`position_side`、`quantity`、`price`、`fee`、
`realized_pnl`（本笔记账的已实现盈亏增量）、`filled_at`。

唯一键：`UNIQUE (order_id, fill_id)` —— 重复轮询不会重复计仓（恢复流程依赖这一点）。`filled_at` 建索引。

### position（策略级虚拟持仓）

`id`、`strategy_id`（引用 `strategy.strategy.id`，级联删除）、`instrument_id`、`inst_id`、
`position_side`（`long`/`short`）、`quantity`（非负）、`average_price`、`realized_pnl`、`updated_at`。

唯一键：`UNIQUE (strategy_id, instrument_id, position_side)` —— 策略 × 标的 × 方向。
`quantity = 0` 的行保留而不删除，用于保留历史已实现盈亏；持仓查询过滤 `quantity > 0`。

### reconcile_diff（对账差异）

`id`、`kind`（`position_mismatch`/`order_missing_exchange`/`order_missing_local`）、`strategy_id`（可空）、
`instrument_id`（可空）、`inst_id`、`position_side`（不按方向比时为空串）、`reference`（订单 `client_order_id`，
持仓差异为空串）、`local_value`、`exchange_value`、`detail JSONB`、`status`（`open`/`resolved`）、`detected_at`、
`resolved_at`、`resolved_by`、`note`、`resolve_attempts`。

唯一约束：部分唯一索引 `UNIQUE (kind, inst_id, position_side, reference) WHERE status = 'open'` ——
同一差异只保留一条未结记录，重复对账不叠加；结案后同一差异再次出现会产生新的 open 行，历史结案记录保留。
对账**只记录差异，不改本地数据**；存在 open 差异时真实下单被拒绝（`execution_reconcile_pending`）。

## 10. mcp schema（S11 MCP 服务）

由迁移 `0009_mcp_schema` 建立（同时给 `strategy.strategy` 增加 `paused_at`）。本 schema 只存客户端与调用审计，
不存业务结论：MCP 不产生自己的策略、回测或订单，所有操作都走既有服务并落在对应 schema。

### mcp_clients（MCP 客户端）

`id`、`name`、`token_hash`（`sha256(token)`，**明文不落库**，只在创建响应返回一次）、`scopes JSONB`
（`["read"]` / `["read","operate"]`）、`created_at`、`last_used_at`（可空）、`revoked_at`（可空）。
唯一键：`UNIQUE (token_hash)`——同一令牌不能绑定两个客户端。吊销即写 `revoked_at`，下一次调用立即 401，
客户端行保留用于审计追溯。

### mcp_call_log（调用审计）

`id`、`client_id`（→ `mcp_clients.id`，`ON DELETE CASCADE`）、`tool`（工具名；非 `tools/call` 方法记方法与
资源名）、`args_digest`（参数摘要，不存原始参数，避免把业务数据二次落库）、`status`（`ok`/`error`/`forbidden`）、
`error_code`（可空）、`reason`（可空，如 `missing scope operate`）、`latency_ms`、`created_at`。
索引：`(created_at)`、`(client_id, created_at)`。每次调用（含被拒的越权调用）都写一行；越权调用**只**写审计行，
不产生业务写入。

迁移链完整清单（`backend/alembic/versions/`，`alembic current` 应恒为 `0009_mcp_schema (head)`）：

| 版本 | 内容 |
| --- | --- |
| `0001_initial` | 基础表与 `ops`/`market` 骨架 |
| `0002_market_ops_schema` | 行情、任务账本、审计 |
| `0003_research_schema` | 目标股票、关系快照/边、相对强弱、市场截面 |
| `0004_opportunity_schema` | 扫描批次、机会、聚类 |
| `0005_strategy_schema` | 策略、腿、审批、状态迁移 |
| `0006_backtest_schema` | 回测运行、指标、净值、成交 |
| `0007_risk_schema` | 风控阈值版本与风险事件 |
| `0008_execution_schema` | 订单、成交、虚拟持仓、对账差异 |
| `0009_mcp_schema` | `mcp.mcp_clients`、`mcp.mcp_call_log`、`strategy.strategy.paused_at` |

## 11. 存储量与保留

按 227 个股票类合约、上市日起约 248 天估算：

| 周期 | 保留策略 | 行数量级 |
| --- | --- | --- |
| `1m` | 滚动 90 天 | ~29.4M |
| `5m` | 滚动 90 天 | ~5.9M |
| `15m` | 滚动 90 天 | ~2.0M |
| `1h` | 全量 | ~1.35M |
| `4h` | 全量 | ~0.34M |
| `1d` | 全量 | ~0.06M |

合计约 3900 万行，单机 PostgreSQL 可承载（`(instrument_id, bar, open_time)` 唯一索引）。行数按 227 个股票类合约与约 248 天历史估算；当前实测标的池为 230 个股票类合约且会继续增长，容量评估需随之更新。

保留任务（`app/market/retention.py`）按 `bar` 分组删除早于 cutoff 的行，每批 `batch_size`（默认 5000）提交一次，避免长事务与锁膨胀；`1h/4h/1d` 不参与清理。删除前必须确认对应 `data_source_sync` 已记录覆盖区间。

## 12. 命名与枚举

- 表名小写复数、无前缀（schema 已表达上下文）；字段 `snake_case`。
- 时间字段后缀：`_at` 表示时刻，`_time` 表示 K 线/时段边界，`_date` 表示本地业务日。
- bar 内部枚举固定为 `1m/5m/15m/1h/4h/1d`，与 OKX 的映射只允许出现在 `adapters/okx` 内（`OKX_BAR = {"1h": "1H", "4h": "4H", "1d": "1D"}`）。
