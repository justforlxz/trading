# 行情与合约数据（P1 / S3）

本文件是 P1「行情与合约数据基础」的落地说明：数据从哪来、怎么落库、怎么补齐、
怎么判定好坏，以及当前明确的限制。字段级定义见
[`architecture/data-model.md`](./architecture/data-model.md)，HTTP 契约见
[`architecture/api-contract.md`](./architecture/api-contract.md)。

## 1. 范围与不做什么

P1 只负责「把真实、可追溯的行情落进库，并能查询与判定质量」。

- 做：合约标的同步、合约 K 线采集与回补、真实美股日线、交易日历、覆盖率与数据质量问题。
- 不做：相关性/机会发现/策略/回测（S4+）、真实账户、下单、私有 WebSocket。
- 公开 WebSocket 可后置；当前只有 REST 轮询采集。

## 2. 决策与降级口径（决策 A）

阶段决策固定为 **A**：

1. **真实美股行情以 Yahoo chart v8 为主源**，失败时降级但**必须显式标注**；不得用 OKX
   指数价冒充真实收盘价。
2. **全部 SWAP 标的入库**并打 `asset_class` / `exchange`；只有美股正股与 ETF
   （`us_equity` + `etf`）参与后续真实相关性分析。
3. **接受 OKX 合约上市日以来的历史深度**（AAPL 约 248 根日线，最早 2026-03-04），
   不做放宽、不拼接假数据，报表如实呈现最早可用时间。

降级行为：

| 场景 | 行为 |
| --- | --- |
| Yahoo 请求失败/超时/限流 | 跳过该标的，写 `data_quality_issue(dataset=market.equity_candle, kind=MISSING_SOURCE)`，`job_run.status=partial` |
| Yahoo 返回空结果 | 同上，不写任何 K 线；`MISSING_SOURCE` 以自然日为去重窗口，同一天多次失败只保留一行，恢复成功后自动 `resolved` |
| OKX 限流（HTTP 429 或 HTTP 200 + `code=50011`） | 指数退避重试；耗尽后该标的本轮跳过，写 `GAP` 待补窗口，任务 `partial` |
| 标的无真实行情映射（私营公司/指数/商品等） | 不建 `equity_asset`，自然不采集 |
| 未知股票符号 | `asset_class=unclassified`，`exchange=NULL`，**不猜**交易所与类别 |

## 3. 数据字典（S3 新增/使用的表）

所有时间列为 `TIMESTAMPTZ`（UTC），API 以 ISO-8601 返回；价格 `NUMERIC(20,10)`、
数量/金额 `NUMERIC(24,10)`、比率 `NUMERIC(12,10)`、基差 `NUMERIC(12,4)`。Python 侧
统一 `Decimal`，API 返回字符串。

### market.instrument（合约标的）

OKX SWAP 全量标的。关键列：`inst_id`（唯一）、`inst_category`（1 加密 / 3 股票 /
4 商品 …）、`asset_class`、`exchange`、合约参数（`ct_val`/`lot_sz`/`min_sz`/`tick_sz`/
`lever`）、`state`、`rule_type`、`list_time`、`source_synced_at`（**每次同步必更新，
API 必返且非空**）、`raw`（OKX 原始条目，仅内部保留，不对外透传）。

幂等：按 `inst_id` upsert；内容未变时同样刷新 `source_synced_at`。

### market.equity_asset（真实标的映射）

`symbol` + `exchange` 唯一（`NULLS NOT DISTINCT`，避免 NULL 重复行）、`currency`、
`timezone`、`source_symbol`、`source_name`（`yahoo` / `none`）、`mapping_status`
（`mapped` / `unmapped` / `private`）。只为 `us_equity` 与 `etf` 建行。

### market.candle（合约 K 线）

`instrument_id` FK、`bar`、`open_time`、OHLC、`vol`/`vol_ccy`/`vol_ccy_quote`、
`confirm`、`source`（`okx_rest` / `okx_history`）、`ingested_at`。
唯一键 `(instrument_id, bar, open_time)`，`ON CONFLICT DO UPDATE`。

规则：

- `confirm=false` 只允许**最后一根**未完成 bar；一旦写过 `confirm=true`，后来的
  未完成版本不会覆盖它（`confirm` 单调 false→true）。
- 重复回补只更新数值，**不产生副本**，不删插。
- 美股永续 24/7 成交：交易日历只用于分析语义，采集不因 `CLOSED` 停摆。

### market.equity_candle（真实股票 K 线）

`equity_asset_id` FK、`interval`（`1m` / `1d`）、`ts`、OHLC、`volume`、`session`
（`PRE`/`REGULAR`/`POST`）、`source`、`ingested_at`。唯一键
`(equity_asset_id, interval, ts)`。

### market.market_session（交易日历）

`venue`（P1 只有 `XNYS`）、`trading_date`、`pre/regular/post` 六条边界、
`is_half_day`、`is_holiday`、`calendar_source`（`builtin:us-equity-v1`）、
`calendar_version`。唯一键 `(venue, trading_date)`。

规则由 `backend/app/market/core/calendar.py` 以纯函数实现（DST、节假日、观测日、
半日市、临时休市），`exchange_calendars` 仅作为**测试 oracle**，不进入运行时。

### market.basis_snapshot（基差）

`instrument_id` FK、`symbol`、`ts`（真实行情时间）、`okx_price`、`equity_price`、
`basis_bps = (okx / equity - 1) * 10000`、`source`。唯一键 `(instrument_id, ts)`。
`|basis_bps| > basis_alert_bps`（默认 500）时写 `OUTLIER` 问题。

### market.data_source_sync（采集账本）

`source`、`dataset`、`scope`、`window_start`/`window_end`、`status`
（`running`/`ok`/`partial`/`failed`）、`attempts`、`rows_written`、`last_error`、
`last_success_at`、`coverage JSONB`。唯一键
`(source, dataset, scope, window_start, window_end)`。

写入规则：标的同步按「自然日 + scope=SWAP」，合约 K 线与真实行情按
「自然日 + `inst_id:bar` / `symbol:1d`」，回补按请求的 `[start,end)`。
`GET /market/sync-status` 取每个组合的最新一行，用数据集间隔 ×3 判定 `stale`，
并提供 `last_success_at` / `age_seconds` 回答「采集延迟」。

### market.data_quality_issue（数据质量）

`dataset`、`scope_id`、`kind`（`GAP`/`DUPLICATE`/`OUTLIER`/`STALE`/`UNCONFIRMED`/
`MISSING_SOURCE`）、`severity`、`window_start`/`window_end`、`detail JSONB`、
`detected_at`、`last_seen_at`、`resolved_at`。唯一键
`(dataset, scope_id, kind, window_start)`：同一缺口反复检测只刷新 `last_seen_at`。

### ops.job_run（任务账本）

`job_name` + `job_key` 唯一，`job_key = sha256("job_name:" + 参数规范化 JSON)`。
`status` ∈ `queued`/`running`/`ok`/`partial`/`failed`/`skipped`。同一参数重复提交
不会新建任务：API 返回 200 + `status=skipped`。

## 4. bar 归一化规则

内部枚举固定为 **`1m / 5m / 15m / 1h / 4h / 1d`**（`app/market/core/bars.py`）。

- 对外 API 接受常见别名，大小写不敏感：`1min`/`1minute`→`1m`、`5min`→`5m`、
  `15min`→`15m`、`60m`/`1hour`→`1h`、`240m`/`4hour`→`4h`、`1day`/`24h`→`1d`。
- 不支持的值（例如 `8H`、`2h`）一律 400 `UNSUPPORTED_BAR`，不做近似映射。
- OKX 原始写法只在 `app/adapters/okx/bars.py` 出现：
  `1h→1H`、`4h→4H`、`1d→1D`，分钟周期同名。**OKX 没有 8H。**
- `1D` 是 **UTC+8 锚**的自然日（首根为 `2026-11-05T16:00:00Z`），不是 `1Dutc`；
  内部只用 `1d` 一种，不混用两个锚点。

## 5. 来源台账（真实抓取记录）

| 数据集 | 来源 | 抓取时间 | 可回溯范围 | 备注 |
| --- | --- | --- | --- | --- |
| `market.instrument` | `GET https://www.okx.com/api/v5/public/instruments?instType=SWAP` | 2026-11-06T13:50Z | 当前快照 | 543 条；`instCategory=3` 为 230 条（S1 记录为 540/227，池会增长） |
| `market.candle`（1m–4h） | `GET /api/v5/market/candles` | 2026-11-06T14:24Z | 最近 300 根/请求 | 40 次/2s；超限 HTTP 429 |
| `market.candle`（1d/回补） | `GET /api/v5/market/history-candles` | 2026-11-06T14:24Z | 上市日至今（AAPL 约 248 根，最早 2026-03-04） | 20 次/2s；超限 HTTP 200 + `code=50011`；`after` 游标翻页 |
| `market.equity_candle` | `GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}` | 2026-11-06T14:24Z | Yahoo 提供的 `range` 窗口 | 免 key；需 UA；无 SLA；`v7/quote` 返回 401 不可用 |
| `market.basis_snapshot` | 上述两源同刻价格 | 运行时 | 运行时 | OKX `last` vs Yahoo `regularMarketPrice`；实测 2026-11-06 约 0.26% |

离线单测使用 `backend/tests/market/fixtures/` 中**原样录制**的响应（每个文件带
`_meta.source` / `_meta.fetched_at`），不编造行情。

不采集、不存储：OKX 私有接口、下单接口、账户数据。

## 6. 采集与回补

- 增量：`ingest_recent` 每标的每周期取最近 300 根，upsert 后按窗口登记缺口。
- 回补：`backfill` 用 `history-candles` 的 `after` 游标翻页，覆盖 `[start, end)`。
- 失败：限流与 5xx 走同一套指数退避（`RetryPolicy`），耗尽抛
  `UpstreamUnavailable`；任务收敛 `partial`，并写 `GAP` 待补窗口（起点=最后一根
  之后，与后续缺口检测同口径，补齐后自然收敛）。
- 调度：`sync_instruments` 每小时、`ingest_candles` 每分钟、`sync_equity` 每 5 分钟、
  `quality_scan` 每 15 分钟、`sync_sessions` 每天、`purge_rolling_candles` 每天；
  用 Redis `SET NX EX` 租约保证多副本不重复投递。调度投递的函数名必须与 worker
  注册名一致（有单测守护）。
- 每个周期任务先写一行 `ops.job_run`（`scheduled_at` 参与 job_key，因此每轮唯一），
  再把 `run_id` 传给 worker；采集成败、耗时与 partial 原因都可在 `/ops/job-runs`
  与 `/market/sync-status` 查到。
- 真实行情周期同步只覆盖 `equity_sync_symbols`（默认 AAPL/SPY/QQQ/NVDA/TSLA）：
  `equity_asset` 映射覆盖全部美股正股与 ETF，但 P1 不每 5 分钟对 175 个标的打满
  Yahoo 的无 SLA 接口。需要更多标的时改配置，不改代码。

## 7. 覆盖率与数据质量

- `GET /market/coverage?inst_id=&bar=&start=&end=`：按 UTC 自然日切桶，返回
  `expected` / `actual` / `missing` / `ratio`，缺口定位到具体 `window_start`。
- `GET /market/quality-issues`：可按 `dataset`、`scope_id`、`kind`、`status=open|resolved` 过滤。
- 质量扫描：`STALE`（最后一根超过 3 个周期）与 `OUTLIER`（相邻收盘跳变超过 20%）。
- 缺口与问题登记都幂等：重复扫描不产生重复行。
- 关闭链路：缺口补齐后同窗口的 `GAP` 自动置 `resolved`；`STALE` 在采集恢复后
  自动关闭；`MISSING_SOURCE` 在数据源恢复后关闭。历史行保留，不物理删除。
- `GET /market/quality-issues?status=open|resolved` 可按状态过滤。

## 8. 保留策略

| 周期 | 保留 |
| --- | --- |
| `1m` / `5m` / `15m` | 滚动 90 天 |
| `1h` / `4h` / `1d` | 全量 |

实现为**行级批量 `DELETE`**（每批 5000 行，逐批提交），不是「按月删除分区」——
`candle` 不分区的原因见 `architecture/data-model.md` §2 candle 的偏差说明。

## 9. 明确限制（必须如实呈现）

1. **历史深度受上市日限制**：AAPL 日线最早 2026-03-04（约 248 根），更早的合约
   K 线在 OKX 不存在；报表与回测必须显示 `first_available`，不得外推。
2. **真实行情源无 SLA**：Yahoo chart v8 免 key 但有 IP 限流，失败即
   `MISSING_SOURCE`；OKX `index-tickers.idxPx` 是交易所自推导指数，**不是**真实收盘价。
3. **分类表需人工维护**：少数新上市符号暂为 `unclassified`（`exchange=NULL`），
   只有显式维护进 `app/market/core/classification.py` 才会升级为具体类别；未知符号
   不会被猜成美股正股。
4. **标的池会增长**：`instCategory=3` 从 227 涨到 230；代码与测试不硬编码数量，
   断言与上游一致性。
5. **不做实时推送**：采集是轮询，端到端延迟取决于调度间隔（1m 周期约 1 分钟）。
6. **Yahoo 数值精度**：上游返回 float32 尾数（如 `344.1700134277344`），落库前
   量化到 `1e-4`，不做价格修正。
7. **手动重跑的幂等键**：`POST /sync/instruments` 不带 `Idempotency-Key` 时参数恒定，
   成功后再次提交会返回 `skipped`；需要强制重跑请换一个 `Idempotency-Key`
   （失败/部分失败的同键任务会自动重试，不需要换 Key）。

## 10. 验收命令

```bash
# 单测（需要 PostgreSQL；TEST_DATABASE_URL 缺省由 DATABASE_URL 换库名为 trading_test）
docker compose --profile dev run --rm --no-deps api-dev pytest -q
docker compose --profile dev run --rm --no-deps api-dev sh -lc 'ruff check . && ruff format --check .'

# 真实行情源探针（免 key，只用标准库）
python3 scripts/probes/equity_probe.py chart AAPL 1d 5d

# 运行中的 API
curl -s 'localhost:8000/api/v1/market/instruments?limit=5'
curl -s 'localhost:8000/api/v1/market/candles?inst_id=AAPL-USDT-SWAP&bar=1h&limit=10'
curl -s 'localhost:8000/api/v1/market/sessions?from=2026-03-01&to=2026-03-20'
curl -s 'localhost:8000/api/v1/market/basis?inst_id=AAPL-USDT-SWAP'
```
