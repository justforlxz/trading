# 外部依赖与风险（P1）

本文的每条结论都来自 2026-11-06 的实测，命令与采集时间一并记录，可用 `scripts/probes/` 复现。任何"官方文档这么写"但没有实测的条目都会明确标注为**未验证**。

## 1. 调研方法

| 项 | 值 |
| --- | --- |
| 采集时间 | 2026-11-06T03:59:15Z ~ 03:59:27Z（UTC），另有 03:52~03:54Z 的补充采集 |
| 网络环境 | 本机直连，无代理 |
| 工具 | `curl` / Python 3 `urllib`（脚本见 `scripts/probes/okx_probe.py`、`scripts/probes/equity_probe.py`） |
| 原则 | 只读、无 API key、不重试掩盖失败；失败原样记录 |

复现：

```bash
python3 scripts/probes/okx_probe.py all
python3 scripts/probes/equity_probe.py all
```

## 2. OKX 美股永续合约

### 2.1 结论速览

| 问题 | 结论 | 证据 |
| --- | --- | --- |
| OKX 是否提供美股永续合约 | **是**。`instType=SWAP` 共 540 个，其中 `instCategory=3`（Stocks）**227 个** | §2.2 |
| 是否包含目标股票 | 是，含 AAPL / GOOGL / MSFT / NVDA / TSLA / SPY / QQQ 等；也含亚洲股、ETF、指数与私营公司（OPENAI、ANTHROPIC） | §2.2 |
| 是否 24/7 可交易 | **是**。美股休市时段（22:52 EST）仍有 ticker 更新与 1m 成交 | §2.3 |
| 公开行情是否需要鉴权 | **不需要**。`/market/*`、`/public/*` 均匿名可用 | §2.6 |
| K 线周期 | `1m/3m/5m/15m/30m/1H/2H/4H` + `6H/12H/1D/2D/3D/1W/1M/3M`（UTC+8 锚）+ 对应 `utc` 变体；**没有 `8H`** | §2.4 |
| 历史深度 | 自标的上市日起。AAPL 仅 **248 根日线**（2026-03-04 起） | §2.5 |
| 限流 | `/market/candles` 40 req/2s、`/market/history-candles` 20 req/2s（按 IP）；实测会返回 429 与 `code=50011` | §2.7 |
| 资金费率 | 8 小时结算一次，但**没有 8H K 线**，回测需自行按 8 小时窗口切分 | §2.8 |

### 2.2 合约清单（采集 2026-11-06T03:59:15Z）

```bash
curl -s 'https://www.okx.com/api/v5/public/instruments?instType=SWAP'
```

结果：HTTP 200，588,290 bytes，1.02s，`code: "0"`，共 **540** 条。

| `instCategory` | 含义（官方文档） | 数量 |
| --- | --- | --- |
| `1` | Crypto | 304 |
| `3` | Stocks | **227** |
| `4` | Commodities | 9 |

文档出处：OKX API v5《Public Data — Get instruments》，字段 `instCategory`：`1` Crypto、`3` Stocks、`4` Commodities、`5` Forex、`6` Bonds、空字符串表示不可用。
<https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments>

`AAPL-USDT-SWAP` 原始样本（节选，字段名与值原样保留）：

```json
{
  "instId": "AAPL-USDT-SWAP",
  "instType": "SWAP",
  "instFamily": "AAPL-USDT",
  "uly": "AAPL-USDT",
  "instCategory": "3",
  "ctType": "linear",
  "ctVal": "1",
  "ctValCcy": "AAPL",
  "settleCcy": "USDT",
  "lotSz": "0.01",
  "minSz": "0.01",
  "tickSz": "0.01",
  "lever": "20",
  "state": "live",
  "ruleType": "normal",
  "listTime": "1772612100000",
  "posLmtAmt": "350000",
  "maxMktSz": "640",
  "maxLmtSz": "100000000",
  "instIdCode": 251760
}
```

227 个 `instCategory=3` 标的构成（实测归类）：

- 美股正股：AAPL、GOOGL、MSFT、NVDA、TSLA、AMZN、META、AMD、INTC、MU、ORCL、PLTR、COIN、MSTR…
- ETF / 指数：SPY、QQQ、IWM、SMH、SOXL、SOXS、TQQQ、SQQQ、TLT、XLE、XBI、EWJ/EWY/EWZ（国家 ETF）、US500、US100、JP225、KR200
- 非美股正股：SONY、SAMSUNG、SKHYNIX、HYUNDAI、NAVER、BIDU、PDD、XIAOMI、SOFTBANK、MURATA、KIOXIA、HANMI…
- 私营/未上市映射：**OPENAI**、**ANTHROPIC**、ZHIPU、MOONSHOT、MINIMAX、SHEIN、POPMART、UNITREE
- 2 倍杠杆 ETF 类：TSLL、NVDL、MSTU、MVLL、KORU、CSOPSKHYNIX2L、CSOPSAMSUNG2L

这直接影响"股票关系分析"的口径：227 个标的不能一律当作美股正股，必须按 `asset_class` + `exchange` 分类，见 §5 决策 2。

### 2.3 24/7 交易证据

美股当时处于休市（2026-11-05 22:52 EST）：

```bash
curl -s 'https://www.okx.com/api/v5/market/ticker?instId=AAPL-USDT-SWAP'
# [2026-11-06T03:59:15Z] HTTP 200
{"instId":"AAPL-USDT-SWAP","last":"343.28","askPx":"343.28","bidPx":"343.27","vol24h":"81663.97","ts":"1793937554068","sodUtc0":"344.58"}
```

1 分钟 K 线（同一时段，含成交）：

```bash
curl -s 'https://www.okx.com/api/v5/market/candles?instId=AAPL-USDT-SWAP&bar=1m&limit=5'
# [2026-11-06T03:59:16Z] rows=5
{"open_time":"1793937540000","o":"343.28","h":"343.28","l":"343.28","c":"343.28","vol":"0","confirm":"0"}
{"open_time":"1793937480000","o":"343.39","h":"343.39","l":"343.28","c":"343.28","vol":"8.57","confirm":"1"}
{"open_time":"1793937420000","o":"343.50","h":"343.57","l":"343.42","c":"343.42","vol":"13.56","confirm":"1"}
```

结论：合约在美股休市时仍持续成交，**不能**用美股交易时段限制合约行情采集；交易时段是"分析语义"（区分真实股票主导 vs 合约自身流动性），不是采集开关。

### 2.4 K 线周期与时间锚定

官方文档《Market Data — Get candles》的 `bar` 取值（实测全部可用）：

- 分钟/小时：`1m`、`3m`、`5m`、`15m`、`30m`、`1H`、`2H`、`4H`
- UTC+8 锚：`6H`、`12H`、`1D`、`2D`、`3D`、`1W`、`1M`、`3M`
- UTC+0 锚：`6Hutc`、`12Hutc`、`1Dutc`、`2Dutc`、`3Dutc`、`1Wutc`、`1Mutc`、`3Mutc`
- `limit` 默认 100，**最大 300**

实测锚定差异：

| 请求 | 首根 `open_time` | 换算 |
| --- | --- | --- |
| `bar=1D` | `1793894400000` | 2026-11-05 16:00Z = 2026-11-06 00:00 **UTC+8** |
| `bar=1Dutc` | `1793923200000` | 2026-11-06 00:00 **UTC** |

`bar=8H` 返回 `{"code":"51000","msg":"Parameter bar error"}` —— **8H 周期不存在**。

对设计的影响：内部只保留一种日线锚定（`1d` → OKX `1D`），不得混存 `1Dutc`；资金费率按 8 小时结算但没有对应 K 线，回测中自行切分（见 `docs/architecture/data-model.md` §1.1）。

### 2.5 历史深度（采集 2026-11-06T03:59:17Z ~ 03:59:19Z）

```bash
# 用 after 游标翻页
/api/v5/market/history-candles?instId=AAPL-USDT-SWAP&bar=1D&limit=100
```

| 页 | 条数 | 最新 `open_time` | 最旧 `open_time` |
| --- | --- | --- | --- |
| 1 | 100 | 1793894400000 | 1785340800000 |
| 2 | 100 | 1785254400000 | 1776700800000 |
| 3 | 48 | 1776614400000 | 1772553600000 |
| 4 | 0 | — | — |

合计 **248 根日线**，最早 `1772553600000` = **2026-03-04**，与该标的 `listTime=1772612100000` 吻合。

结论：历史深度 = 上市以来，不是"OKX 提供 N 年"。任何更长样本的回测都不能用该合约完成；P1 回测样本上限约 248 天（日线），日内可用 1h/4h 提升样本内频次。这是硬约束，见 §5 决策 3。

### 2.6 鉴权边界

官方文档《Market Data》章节明确："The API endpoints of Market Data do not require authentication." 实测 `instruments`/`ticker`/`candles`/`funding-rate` 均匿名 200。

- P1 只使用公开行情（`/market/*`、`/public/*`），**不持有任何 API key**，账户级接口（下单、持仓、资金）在 P3 之前不接入。
- `x-simulated-trading: 1` 请求头在公开接口上被接受（返回与实盘一致的数据），但这不构成模拟交易的验证 —— P1 不做模拟盘。

### 2.7 限流（实测）

| 接口 | 文档限流 | 实测 |
| --- | --- | --- |
| `/api/v5/market/candles` | 40 次 / 2s（按 IP） | 70 个并发请求：50 次 HTTP 200，**20 次 HTTP 429**；60 并发：10 个响应体 `{"code":"50011","msg":"Too Many Requests"}` |
| `/api/v5/market/history-candles` | 20 次 / 2s（按 IP） | 回补 248 根日线分 3 页，间隔 0.2s，全部 200 |

注意失败形态有两种：HTTP 429 与 HTTP 200 但 `code=50011`。适配器必须同时处理，不能只看状态码。这也意味着全量回补必须是后台任务 + 分片 + 指数退避（见 `docs/plan/p1.md` P1-02）。

### 2.8 资金费率与指数

```bash
curl -s 'https://www.okx.com/api/v5/public/funding-rate?instId=AAPL-USDT-SWAP'
# [2026-11-06T03:59:17Z]
{"instId":"AAPL-USDT-SWAP","fundingRate":"0.0000000000000000","fundingTime":"1793952000000","nextFundingTime":"1793980800000"}
```

`1793952000000` = 2026-11-06 08:00Z，`1793980800000` = 16:00Z，间隔 8 小时。

指数与标记价可用：`/api/v5/public/mark-price`（AAPL `markPx 343.61`）、`/api/v5/market/index-tickers?instId=AAPL-USDT`（`idxPx 343.61`）、`/api/v5/market/index-candles`。该指数由 OKX 自身市场推导，**不等于真实美股收盘价**，只能作为降级口径（见决策 1）。

另外官方文档提到 `adjust=forward` "only applicable to equity perpetual contracts"，用于拆股导致的成交量/价格调整（`vol`/`volCcy` 按比例调整，`volCcyQuote` 不调整）。P1 只做读取，遇到拆股需要按该参数重新对齐历史序列——**未实测**（调研期内没有发生拆股），列为 S3 的实现注意事项。

### 2.9 与真实股价的可比性（采集 2026-11-06T03:59:26Z）

| 来源 | 值 |
| --- | --- |
| OKX `AAPL-USDT-SWAP` last | 343.28 |
| Yahoo `AAPL` `regularMarketPrice` | 344.17 |
| 基差 | 约 **0.26%**（同一时刻，合约相对现货折价） |

说明合约价能跟踪真实股票，但存在基差与 24/7 溢价/折价。相关性分析必须显式记录用的是 `okx_close` 还是 `equity_close`（`relation_snapshot.price_basis`），两者不可混算。

## 3. 真实美股行情源

### 3.1 实测结果

| 源 | 端点 | 结果 | 结论 |
| --- | --- | --- | --- |
| Yahoo Finance chart v8 | `https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d` | HTTP 200，1.72KB | **可用**，无需 key（需带 UA） |
| Yahoo chart v8（含盘前盘后） | `...&interval=1m&range=1d&includePrePost=true` | HTTP 200，896 点，`currentTradingPeriod` 给出 pre/regular/post 边界 | 可用，且自带时段窗口 |
| Yahoo v7 quote | `https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL` | HTTP **401** `Unauthorized` | 不可用（需 crumb/cookie），禁止采用 |
| Stooq CSV | `https://stooq.com/q/d/l/?s=aapl.us&i=d` | HTTP 200 但返回 JS proof-of-work 挑战页，无 CSV | 不可用 |
| Alpha Vantage | `.../query?function=TIME_SERIES_DAILY&symbol=AAPL` | `{"Error Message":"...apikey is invalid or missing"}` | 需 key（免费额度有限），未采用 |
| Finnhub | `https://finnhub.io/api/v1/quote?symbol=AAPL` | HTTP 401 `{"error":"Please use an API key."}` | 需 token，未采用 |

Yahoo chart v8 样本（`interval=1d&range=5d`）：

```json
{
  "meta": {
    "symbol": "AAPL", "currency": "USD", "exchangeName": "NMS",
    "instrumentType": "EQUITY", "exchangeTimezoneName": "America/New_York",
    "gmtoffset": -18000, "regularMarketPrice": 344.17,
    "regularMarketTime": 1793912401, "hasPrePostMarketData": true
  },
  "points": 5,
  "first_ts": 1793367000, "last_ts": 1793889000,
  "first_close": 344.63, "last_close": 344.17
}
```

`includePrePost=true` 时 `currentTradingPeriod`（EST，2026-11-05）：

```json
{"pre":{"start":1793869200,"end":1793889000},
 "regular":{"start":1793889000,"end":1793912400},
 "post":{"start":1793912400,"end":1793926800}}
```

即盘前 04:00–09:30、常规 09:30–16:00、盘后 16:00–20:00（本地时间），可用于交叉校验自建日历（`market_session`）。

### 3.2 结论

1. P1 唯一可用的免 key 真实行情源是 Yahoo chart v8（非官方），**没有 SLA、没有配额承诺、可能随时失效或封禁**。
2. 该源只用于"关系分析的真实股价基准"和"时段交叉校验"，**不是**交易价格的来源；交易与回测一律用 OKX 合约价。
3. 必须实现为可切换适配器：`EquityDataSource` 协议 + `yahoo` 实现 + `none` 实现（返回 `MISSING_SOURCE`），失败时降级而不是编造数据。
4. 免费 key 源（Alpha Vantage 等）在额度、延迟、字段覆盖上均不满足全市场 227 标的的日更需求；付费源超出"不引入付费商业服务"的约束。

## 4. 风险

| 风险 | 等级 | 说明 | 缓解 |
| --- | --- | --- | --- |
| 真实行情源非官方、无 SLA | 高 | 端点变更/限流/封禁会直接影响关系分析 | 可切换适配器 + 降级标记 + 缓存已采数据；决策项 1 |
| 合约历史过短（248 天） | 高 | 回测统计显著性弱 | 多窗口 + walk-forward + 报告显式声明；决策项 3 |
| OKX 限流与错误码双形态 | 中 | 回补失败或静默丢数据 | 后台任务 + 退避 + `data_source_sync` 账本 + 缺口检测 |
| 标的分类混杂 | 中 | 相关性口径错误 | `asset_class`/`exchange` 强制分类；决策项 2 |
| P1 API 无鉴权 | 中 | 内网暴露时可被任意读取 | 部署侧绑定 127.0.0.1/内网；S2 起在反代层限制来源；鉴权留到多用户需求出现时再做 |
| 拆股导致历史序列不连续 | 低 | 相关性/回测失真 | 使用 `adjust=forward` 重新对齐（未实测）；在数据质量报表中标记 |
| OKX 服务条款对程序化访问的限制 | 未验证 | 无法从公开文档确认个人自用自动化采集是否被允许 | 仅使用公开行情、低频采集、不接入交易；如需商用再评估 |

## 5. 需 lxz 决策（3 项）

### 决策 1：真实美股行情源选型

| 选项 | 说明 | 影响 |
| --- | --- | --- |
| A（建议） | Yahoo chart v8 作为主源，适配器可切换，缓存已采数据，失败降级到 OKX 指数并在 UI 标注 | 零成本、字段够用；但无 SLA，可能中途失效，需要接受"关系分析可能降级" |
| B | 申请免费 key 源（Alpha Vantage 等）作为主源 | 有配额与稳定性预期；但 5 次/分钟级别的额度无法支撑 227 标的日更，需额外缓存层 |
| C | 只用 OKX 内部指数 | 完全自洽、无外部依赖；但指数由合约市场推导，无法反映真实美股关系，"发现股票关系"这一核心价值被削弱 |

建议 A：先跑通真实关系，同时把"源不可用"作为显式状态暴露，而不是假装有数据。

### 决策 2：标的口径范围

| 选项 | 说明 | 影响 |
| --- | --- | --- |
| A（建议） | 227 个 `instCategory=3` 全部入库并打 `asset_class`/`exchange`；仅 `us_equity`/`etf` 参与真实行情相关性，其余降级 OKX 指数口径 | 扫描广度最大、口径可解释；需要维护分类表 |
| B | 只保留美股正股 + 美股 ETF（约 150 个），其余不同步 | 口径最干净；但会漏掉亚洲股与指数联动信号，且 `OPENAI` 这类热门标的不可用 |

建议 A：分类成本一次性，收益是"全市场"这个产品承诺成立。

### 决策 3：历史深度不足的应对

| 选项 | 说明 | 影响 |
| --- | --- | --- |
| A（建议） | 接受 248 天日线 + 1h/4h 日内样本，回测报告显式声明样本区间与显著性限制 | 立即推进；结论外推能力有限 |
| B | 用 1m/5m 拼接更长"等效样本"（用高频重采样扩样本） | 样本数变多但时间跨度不变，统计意义提升有限，且实现复杂 |
| C | 等待/寻找更长历史的替代数据源 | 阻塞 P1；且没有免 key 的合规长历史源 |

建议 A：把限制写进验收报告，比用错误方法伪造长度更可靠。

## 6. 采集记录

| 时间（UTC） | 命令/端点 | 结果 |
| --- | --- | --- |
| 2026-11-06T03:59:15Z | `GET /api/v5/public/instruments?instType=SWAP` | 200，540 条，227 股票类 |
| 2026-11-06T03:59:15Z | `GET /api/v5/market/ticker?instId=AAPL-USDT-SWAP` | 200，last 343.28 |
| 2026-11-06T03:59:16Z | `GET /api/v5/market/candles?...bar=1m&limit=5` | 200，5 根，含成交量 |
| 2026-11-06T03:59:16Z | `GET /api/v5/market/candles?...bar=1D&limit=5` | 200，首根 2026-11-05 16:00Z（UTC+8 锚） |
| 2026-11-06T03:59:17Z | `GET /api/v5/public/funding-rate?instId=AAPL-USDT-SWAP` | 200，8 小时周期 |
| 2026-11-06T03:59:17Z | `GET /api/v5/market/history-candles?...bar=1D`（3 页） | 248 根，最早 2026-03-04 |
| 2026-11-06T03:59:26Z | `GET query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d` | 200，5 点 |
| 2026-11-06T03:59:26Z | 同上 `interval=1m&range=1d&includePrePost=true` | 200，896 点，含时段边界 |
| 2026-11-06T03:59:27Z | `GET query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL` | 401 Unauthorized |
