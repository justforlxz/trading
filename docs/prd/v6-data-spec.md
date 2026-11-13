# trading 产品功能与数据需求说明

> 版本：v1.0  
> 基准原型：Trading Dashboard v6  
> 目的：把原型中的页面、功能、数据字段、数据来源、计算方式和更新机制记录下来，作为后端设计及 Multica Issue 拆分依据。  
> 说明：原型中的价格、账户、持仓、指标、信号、新闻事件、回测记录均为演示数据，不代表真实行情或真实交易结果。

---

## 1. 产品范围

`trading` 是个人使用的自托管交易工作台。当前原型围绕以下能力组织：

- 市场概览：查看美股大盘、波动率、加密市场与市场状态。
- 自选与分析：维护关注标的，查看 K 线、技术指标、相关性和近期事件。
- 账户与持仓：读取 OKX 账户、持仓和风险信息；同时维护非 OKX 的手动持仓。
- 策略与回测：定义规则、选择标的和回测区间，查看回测结果。
- 研究记录：记录假设、回测结论、决策和交易复盘。
- 提醒与活动：汇总指标信号、风险事件、策略事件和系统同步事件。
- 设置与数据健康：配置数据连接、显示偏好、风险默认值，查看数据同步状态。

### 当前原型没有实现的能力

以下内容不要因为设置页或产品愿景而被误认为 v6 已经包含：

- 实际下单、撤单、改单、平仓。
- 策略自动执行或自动管理订单。
- 多用户、权限角色、SaaS 租户。
- 复杂的多交易所统一账户和跨交易所执行。

v6 的 OKX 持仓区是只读；手动持仓是本系统自己的记账数据；策略当前只用于生成观察信号和回测。实际交易执行应作为单独阶段，经过风控与权限设计后再开发。

---

## 2. 开发前必须统一的基础约定

### 2.1 统一标的身份，不以页面显示代码作为主键

原型混用了 `XAAPL-USDT`、`AAPL-USDT-SWAP` 等演示标识。后端必须把内部标的 ID、交易所合约 ID、展示代码分开保存：

| 字段 | 示例 | 用途 |
|---|---|---|
| `instrument_id` | 内部 UUID | 系统内部稳定主键 |
| `venue` | `OKX` | 数据/交易场所 |
| `inst_id` | 以 OKX instruments API 返回为准 | OKX 原始合约 ID |
| `inst_type` | `SWAP` | 合约类型 |
| `base_asset` | `AAPL` | 标的资产代码 |
| `quote_asset` | `USDT` | 计价资产 |
| `display_symbol` | `AAPL-USDT` | UI 展示代码，可独立调整 |
| `asset_class` | `us_stock_perpetual` | 股票永续、加密现货、加密永续等分类 |
| `name` | Apple | 展示名称 |

**获取方式：**从 OKX `GET /api/v5/public/instruments?instType=SWAP` 动态发现合约，并保存 `instId`、`ctVal`、`ctMult`、`tickSz`、`lotSz`、`minSz`、`settleCcy`、`state` 等合约规格。定期刷新，并处理上架、下架、规格变更。不可把 `XAAPL` 这种展示代码硬编码成真实交易所 ID。

OKX 股票永续产品说明提到交易对采用 `[TICKER]USDT` 格式，且产品对不同用户/地区的适用性可能不同；因此启动时必须验证 API 返回的实际合约和账户可用性。参考：[OKX Stock Perpetuals](https://www.okx.com/en-us/help/stock-perpetuals)。

### 2.2 价格必须区分 last / mark / index

同一个合约至少有三种不同价格语义：

- `last_price`：最近成交价，适合行情展示和成交参考。
- `mark_price`：标记价格，适合未实现盈亏、强平和风险距离计算。
- `index_price`：指数价格，适合观察合约锚定的参考价格。

不能把三者混成一个 `price` 字段。每条价格数据还要记录 `source`、`as_of`、`received_at` 和延迟/陈旧状态。

### 2.3 K 线必须标明来源、周期和时间口径

- 交易策略、分析和回测优先使用目标 OKX 合约自己的 OHLCV 数据。
- 如需比较股票现货参考价，应作为单独的数据序列保存，不能覆盖永续合约 K 线。
- K 线统一保存 UTC 时间戳，并明确 bar 的边界口径；UI 按北京时间展示。
- 股票永续是 24/7 交易产品，而底层美股有正常交易时段、盘前盘后和节假日。市场时段状态不能用合约是否可交易来代替。
- 每根 K 线至少保存 open/high/low/close/volume、成交额（若提供）、bar 周期、数据源和是否完整。

### 2.4 原始数据与计算结果分开保存

推荐的数据链路：

`外部数据源 → 数据采集/同步 → 原始行情库 → 标准化数据 → 指标/相关性/信号计算 → 产品 API → Web UI`

回测必须读取历史数据库中的标准化数据，并保存本次回测使用的数据版本、策略参数和成本假设，保证结果可复现。

---

## 3. 页面功能与数据需求

## 3.1 首页：市场与账户

| 功能区 | 产品功能 | 展示数据 | 数据来源/计算方式 |
|---|---|---|---|
| 市场概况 | 查看大盘、波动率和加密市场状态 | NASDAQ、S&P 500、DOW、VIX、BTC 的最新值、涨跌额、涨跌幅、市场时段、更新时间 | BTC 用 OKX ticker；美股指数和 VIX 使用外部行情供应商。候选 FMP，需确认对应指数代码、实时权限和授权范围 |
| 账户概览 | 了解账户资金和保证金使用情况 | 账户权益、今日盈亏及比例、可用权益/保证金、已用保证金、未实现盈亏、持仓名义价值、保证金使用率 | OKX 私有 Account API；名义价值根据合约规格和 mark price 计算或采用交易所字段 |
| 风险监控 | 显示组合层面的风险状态 | 综合等级、临近止损持仓数、高杠杆持仓数、最大单标的敞口、未设置止损数量 | 持仓快照 + 本地止损设置 + 风控规则计算 |
| 当前持仓 | 快速查看所有持仓 | 合约、方向、杠杆、未实现盈亏、标记价、止损距离 | OKX 持仓快照；手动持仓表；实时价格 |
| 市场摘要 | 汇总当天市场变化与主要风险 | 标题、要点、关联标的、依据数据、生成时间 | 由行情摘要指标和新闻事件生成；LLM 只负责归纳，不负责创造行情数据 |
| 关注列表摘要 | 查看关注标的核心技术状态 | 价格、日涨跌幅、RSI、趋势、信号 | 行情 + 本地指标计算 + 信号引擎 |
| 需要关注 | 聚合需要用户处理的提醒 | 提醒类型、标的、触发条件、严重程度、触发时间、状态 | 本地 `alert_event`，来源包括技术信号、风险规则、策略信号和数据异常 |
| 策略运行 | 查看策略概况 | 策略总数、启用数、运行状态、待确认信号、近 30 日回测/模拟表现 | 本地策略、扫描任务、回测结果；当前不代表真实自动交易 |
| 最近活动 | 展示最近发生的系统事件 | 事件描述、对象、时间、结果、来源 | 本地 `activity_event` 事件流水 |

### 首页关键计算

- 今日盈亏：不能直接假设 OKX 账户余额接口提供了与 UI 定义完全一致的“今日盈亏”。建议在每日北京时间 00:00 保存账户权益基准快照，计算 `当前 totalEq - 日初 totalEq - 当日净入金/转入`，并通过账户账单/资金流水识别入金、出金和内部划转。若暂时无法完整识别资金流，只能显示“账户权益变化”，不能标成“今日盈亏”。已实现/未实现盈亏应单独定义口径。若用户更希望按 UTC 或美股交易日统计，需要在设置中明确。
- 保证金使用率：定义为 `used_margin / (used_margin + available_margin)` 或采用 OKX 账户风险字段。必须在确定账户模式后固定口径，不要混用 `imr`、`availEq` 和可用余额。
- 最大单标的敞口：`某标的总名义价值 / 组合总名义价值`。另提供 `某标的总名义价值 / 账户权益`，避免两种“敞口比例”概念混淆。
- 市场摘要：需要带 `as_of`、使用的数据源和关联证据。数据不完整时应显示“摘要不完整/未生成”，而不是正常状态。

## 3.2 自选

| 功能 | 展示/输入数据 | 后端工作 |
|---|---|---|
| 搜索标的 | 代码、名称、资产类别、交易所、可交易状态 | 搜索标准化 `instrument` 表；可从 OKX instruments 同步可交易合约 |
| 添加/移除 | `instrument_id`、用户自选分组、排序位置 | 写入/删除 `watchlist_item`；操作生成活动记录 |
| 分类筛选 | 全部、股票永续、加密资产 | 按 `asset_class` 过滤 |
| 排序 | 默认顺序、涨跌幅、价格、RSI | 在查询层或前端按返回字段排序 |
| 自选概览 | 总数、偏多数、偏空数、日线数据覆盖率 | 根据最新已完成 K 线和趋势规则聚合 |
| 市场环境 | 风险偏好、趋势广度、波动状态 | 使用大盘数据和自选标的指标计算，需保存计算时间和规则版本 |
| 信号观察 | 标的、信号、解释、待确认状态 | 来自 `alert_event` / `strategy_signal` |

自选表格字段：`display_symbol`、名称、最新价、日涨跌幅、趋势状态、RSI(14)、ATR(14) 百分比、有效 K 线数量、最近更新时间、数据质量状态。

## 3.3 标的详情与技术分析

| 功能区 | 需要的数据 | 数据如何产生 |
|---|---|---|
| 标的头部 | 标的名称、合约 ID、资产类别、最新价、涨跌额/幅、价格类型、数据时间 | OKX ticker/mark/index 订阅；价格类型需要明确标注 |
| 周期切换 | 1D、4H、1H 等周期可用状态 | 后端查询 K 线覆盖情况；没有完整数据的周期禁用 |
| K 线图 | 时间、OHLC、成交量；MA20 等叠加线 | OKX 历史 K 线 + WebSocket 最新 K 线 |
| 趋势 | Close、MA20、MA60、价格与均线距离、均线斜率 | 本地从 K 线计算 |
| 动量 | RSI(14)、MACD(12,26,9) | 本地从 K 线计算，固定算法版本 |
| 波动 | ATR(14)、ATR/Close、ATR 历史均值 | 本地计算 |
| 成交量 | 当根成交量、20 日均量、相对成交量 | OHLCV 计算 |
| 相对强弱 | 标的 N 日收益、基准 N 日收益、超额收益 | 本地计算；基准应可配置，股票默认可选 QQQ/SPY，加密默认可选 BTC，不要把 BTC 固定为所有资产唯一基准 |
| 关键价位 | 近 20 日高点/低点、距现价百分比 | 本地计算；首版沿用 20 日区间高低点，不包装成预测价 |
| 关联资产 | 关联标的、行业/类别、相关系数、计算窗口 | 对齐交易日/时间窗后，基于收益率序列计算 Pearson 相关系数；缺失样本要剔除并显示有效样本数 |
| 读数 | 对趋势、动量、波动和相关性的文字解释 | 由模板/规则引擎生成；如接 AI，输入必须是已计算的指标快照 |
| 关联策略 | 策略名称、参数、标的关系、最近回测收益、最大回撤、交易数、回测日期 | 本地策略与回测数据库关联查询 |
| 近期事件 | 宏观事件、公司财报、公司公告/新闻，事件时间、影响标的、来源链接 | 宏观事件优先 OKX Economic Calendar 或外部日历；公司财报/新闻用外部数据供应商 |
| 数据覆盖 | 每个周期的起止时间、K 线数量、缺口数量、最后同步时间 | K 线存储与数据质量检查任务 |

### 指标定义（首版固定）

- `MA(n)`：过去 n 根已完成 K 线收盘价简单移动平均。
- `RSI(14)`：Wilder RSI；不可由不同库使用不同平滑口径后直接混用。
- `MACD(12,26,9)`：EMA12 - EMA26，信号线 EMA9，展示 MACD 值/信号线/柱状值。
- `ATR(14)`：Wilder ATR；`ATR_pct = ATR / close * 100%`。
- `relative_strength_20d = symbol_return_20d - benchmark_return_20d`。
- `correlation_60d`：先将标的与基准的收益率按同一时间戳对齐，再计算最近 60 个有效样本的 Pearson 相关系数。
- 趋势标签首版可定义：`close > MA20 && MA20 > MA60` 为偏多；`close < MA20 && MA20 < MA60` 为偏空；其他为中性。阈值必须配置化。

## 3.4 持仓

### OKX 持仓（只读）

| 展示字段 | 后端字段/来源 |
|---|---|
| 合约、资产类别 | OKX positions 的 `instId`，关联 instruments 元数据 |
| 方向 | `posSide` / `pos`，结合账户持仓模式归一化 |
| 数量 | `pos`，并按 `ctVal`/`ctMult` 转换展示单位 |
| 开仓均价 | `avgPx` |
| 标记价 | 持仓 `markPx` 或公共 mark-price 行情 |
| 未实现盈亏 | `upl`、`uplRatio` |
| 杠杆 | `lever` |
| 保证金 | `margin`、`imr` 等字段；按账户模式选择正确口径 |
| 预估强平价 | `liqPx`，仅作为交易所估算值显示 |
| 保证金模式 | `mgnMode`（cross/isolated） |
| 止损价 | 从本地风险设置或 OKX 条件/止损委托读取；不能假设 positions 基础字段一定能提供用户止损价 |

数据源：

- REST：`GET /api/v5/account/balance`、`GET /api/v5/account/positions`。
- WebSocket 私有频道：`account`、`positions` 或 `balance_and_position`，用于接收变化；服务端定时 REST 对账，修复漏推/断线。
- 行情：OKX 公共 WebSocket ticker/mark price。

### 手动持仓（本地记账）

功能：创建手动持仓、买入、卖出、查看操作流水。字段至少包括：

- 持仓：`id`、`instrument_id`、方向、当前数量、平均成本价、创建时间、备注、止损价（可空）、杠杆（可空）、状态。
- 操作流水：`id`、`position_id`、动作（开仓/加仓/减仓/平仓/更正）、数量、成交价、费用（可空）、成交时间、备注、创建时间。
- 每次更改都写入不可覆盖的流水；当前持仓数量和成本由流水计算或在事务中更新。
- 手动持仓当前价格读取公共行情；没有可匹配的 OKX 合约时，需要明确选择外部行情来源，禁止默默用相似标的价格替代。

### 敞口和风险

- 多头名义价值、空头名义价值：按合约规格、mark price 和 position size 归一化后计算。
- 行业敞口：需要 `instrument.sector` / `category` 元数据；首版允许人工维护标的分类。
- 临近止损：分别计算止损价格距离和 ATR 距离。多头：`(mark - stop) / mark`；空头：`(stop - mark) / mark`。ATR 距离 = 价格距离 / ATR。
- 高杠杆：按用户配置阈值比较 `lever`，不能硬编码一个标准适用于全部标的。
- 未设置止损：本地手动持仓的 stop 字段为空，或 OKX 仓位没有关联到有效止损委托。
- 风险等级：由明确的规则和阈值决定，保存触发规则 ID、对象、数值、阈值和严重程度；不要让 AI 单独决定风险等级。

## 3.5 策略与回测

### 策略管理

| 功能 | 需要的数据 |
|---|---|
| 创建策略草稿 | 名称、策略类别、描述、周期、方向、规则集、成本模型、仓位规则 |
| 编辑策略 | 策略版本、参数、规则、变更时间、变更说明 |
| 标的管理 | 策略关联的 `instrument_id` 列表 |
| 策略状态 | 草稿、已验证、已启用、暂停、归档；当前启用不等于真实自动下单 |
| 信号扫描 | 最近扫描时间、覆盖标的数、成功/失败数、待确认信号数 |
| 组合表现 | 组合收益、最大回撤、胜率、盈亏比；必须基于明确组合回测记录 |

策略规则应以可序列化结构保存，不要把规则只存成自然语言。示例：

```json
{
  "timeframe": "1D",
  "direction": "long_only",
  "entry": {
    "all": [
      {"left": "MA(20)", "op": ">", "right": "MA(60)"},
      {"left": "RSI(14)", "op": "<", "right": 65}
    ]
  },
  "exit": {
    "any": [
      {"left": "MA(20)", "op": "<", "right": "MA(60)"},
      {"type": "drawdown_stop", "value": 0.08}
    ]
  },
  "position_sizing": {"type": "equal_weight", "weight": 0.3333, "max_positions": 3}
}
```

### 回测输入

- `strategy_version_id`
- 标的列表
- 周期
- 起止日期
- 初始资金和计价币种
- 手续费率（maker/taker 或统一费率）
- 滑点模型及参数
- 永续资金费率模型/历史数据
- 信号确认和成交时点（原型为收盘确认、下一根 K 线执行）
- 是否允许做空、仓位规则、风险约束

### 回测输出

| 类别 | 字段 |
|---|---|
| 汇总指标 | 总收益、年化收益、最大回撤、夏普、胜率、盈亏比、交易次数、平均持仓时长、最大连亏 |
| 净值序列 | 时间、策略净值、基准净值、回撤 |
| 交易明细 | 标的、方向、开仓时间/价、平仓时间/价、数量、费用、资金费、滑点、毛盈亏、净盈亏、收益率、退出原因 |
| 回放 | 每根 K 线索引、当时指标值、信号、模拟持仓、现金、权益 |
| 稳健性 | 样本内/样本外表现、参数敏感性、手续费压力、滑点压力、数据质量检查 |
| 可复现信息 | 策略版本、数据集版本、运行器版本、参数、成本设置、开始/结束时间、任务日志 |

### 回测数据注意事项

- OKX K 线历史接口可用于获取较长区间的历史 K 线；先进行目标合约可用性和历史深度验证，再决定回测覆盖期。
- OKX 资金费率历史接口文档当前注明最多返回近三个月。若回测时间跨越多年，不能声称已经纳入完整历史资金费率；必须另建资金费率归档、接入有授权的历史数据供应商，或明确标记该部分为假设成本。
- 当前费率、滑点和合约规格不能直接代表历史参数；回测记录必须保存实际使用的假设。
- 股票永续 24/7 交易；若策略逻辑使用美股交易日收盘价，需要明确是 OKX 合约日线还是美股常规交易时段收盘价，二者不能混为一条序列。

## 3.6 回测详情

页面功能：

- 展示回测概要指标和测试口径。
- K 线图展示进出场点。
- 历史回放：播放、暂停、前后单步、速度选择、进度拖动。
- 净值与回撤图：策略净值、基准净值、回撤曲线。
- 交易明细：按盈利/亏损和标的筛选，导出 CSV。
- 稳健性检查和验证清单。
- 写复盘：创建一条关联当前 backtest_id 的研究记录。

后端需提供分页交易明细、按时间索引的 K 线和权益点。回放不应每一步请求一次第三方行情；应从本次回测已保存的输入序列和结果序列读取。

## 3.7 记录 / 研究日志

记录类型：假设、回测结论、决策、复盘。

字段：`id`、`type`、`title`、`content`（Markdown 或安全的结构化内容）、`related_instrument_id`、`related_strategy_id`、`related_backtest_id`、创建时间、更新时间、标签。

功能：创建、编辑、删除、按类型筛选、按时间排序、查看关联对象、查看统计数量。记录内容属于用户数据，不由 AI 自动改写；如提供 AI 辅助总结，必须由用户主动触发并保留原文。

## 3.8 设置与系统健康

| 设置项 | 保存内容 | 后端要求 |
|---|---|---|
| 行情与推送 | Provider、连接状态、订阅标的、最后同步时间、失败次数 | 提供数据源健康检查和同步任务状态 |
| 显示偏好 | 涨跌配色、默认周期、价格精度、首页布局 | 用户级设置，前端可缓存，后端持久化 |
| 交易连接 | OKX API Key/Secret/Passphrase、账户连接状态、权限检测 | Secret 只在服务端加密保存；前端不回显 |
| 自动执行开关 | v6 默认关闭 | 当前版本可以只保存状态，不实现真实下单 |
| 风险默认值 | 默认杠杆、单笔风险预算、预警阈值、止损规则 | 服务端作为策略默认配置；策略实例保存自己的配置快照 |
| 代理/演示数据 | 数据环境标识 | 实盘、模拟、回测、演示数据必须带环境标签，禁止混排 |
| 系统健康 | WebSocket、历史数据、任务队列、数据库、备份状态 | 后端健康检查和同步任务监控 |
| 安全 | API 权限、密钥状态、审计记录 | 禁止提币权限；记录密钥配置变更、策略配置和未来的交易操作 |

---

## 4. 数据源与采集方式

### 4.1 首版数据源方案

| 数据域 | 首选来源 | 获取方式 | 备注 |
|---|---|---|---|
| OKX 股票永续合约列表/规格 | OKX Public API | `GET /api/v5/public/instruments?instType=SWAP`；产品规格变更订阅 instruments channel | 合约 ID 和交易规则以 API 返回为准 |
| OKX 合约实时行情 | OKX Public WebSocket | ticker、mark price、index ticker 等频道；REST 做初始快照/断线恢复 | 后端统一订阅，不让浏览器持有交易所连接 |
| OKX 合约历史 K 线 | OKX Public REST | `/api/v5/market/candles`、`/api/v5/market/history-candles`；补齐缺口 | 对每个目标合约先实测历史起点和周期可用性 |
| OKX 账户余额/权益 | OKX Account API | `GET /api/v5/account/balance` + 私有 account/balance_and_position channel | 需要只读 API Key |
| OKX 持仓 | OKX Account API | `GET /api/v5/account/positions` + 私有 positions channel | 页面只读；定期 REST 对账 |
| OKX 资金费率 | OKX Public API | 当前费率和 funding-rate-history；订阅 funding-rate channel | API 历史窗口有限；长周期回测需另行归档 |
| 美股指数、VIX、底层股票参考价 | 外部行情商，候选 FMP | REST/WS（依供应商能力） | 需确认 NASDAQ Composite、S&P 500、DOW、VIX 的具体 symbol、实时权限、延迟与授权条款 |
| 宏观日历 | OKX Economic Calendar 或 FMP Calendar | REST 定期拉取；若需要可订阅 OKX economic-calendar channel | 统一保存事件时区、重要性、前值/预期/实际值 |
| 公司财报/公司事件 | FMP Calendar 或其他授权供应商 | 按关注标的查询财报日、拆股、分红等事件 | 供应商 coverage/价格/授权需要在接入前确认 |
| 新闻 | FMP Market News 或其他新闻源 | 按关注标的/行业抓取；保存标题、来源、URL、发布时间和 ticker 标签 | AI 只对已抓取的内容做归纳和分类 |
| 技术指标 | 自有计算模块 | 从标准化 OHLCV 计算 | 不需要额外购买指标 API |
| 相关性/市场广度/关键价位 | 自有计算模块 | 从对齐后的历史收益率和指标计算 | 保存计算窗口、样本数和算法版本 |
| 提醒/活动 | 自有事件系统 | 指标、风险、策略、采集任务触发时写入数据库 | 不能仅靠前端临时拼接 |

### 4.2 供应商候选与验证

**OKX** 是合约行情、合约规格和账户数据的权威来源。官方文档列出公共行情、K 线、标记价格、资金费率、账户余额、持仓以及私有 WebSocket 频道：

- [OKX API v5 文档](https://www.okx.com/docs-v5/en/)
- [OKX Stock Perpetuals 产品说明](https://www.okx.com/en-us/help/stock-perpetuals)

**FMP** 可作为外部股票数据的候选统一供应商。其文档列有 Real-time Market Data、Index Market Data、Market Calendar、Market News、Historical Market Data 等数据集；实际使用前需核对具体 symbol、实时/延迟权限、套餐限制和数据使用授权：

- [FMP API Quickstart](https://site.financialmodelingprep.com/developer/docs/quickstart)

不要在未核实前把 FMP 视为已经选定的数据供应商；也不要假设免费套餐可提供所有指数实时数据。

### 4.3 推荐同步频率

以下是系统侧建议值，最终需结合 OKX/外部供应商限频与个人设备资源调整：

| 数据 | 采集/刷新方式 | 建议频率 |
|---|---|---|
| 合约规格 | REST 初始化 + instruments WS | 启动时、每日校验、事件变更 |
| 自选实时价格 | WebSocket | 推送驱动；前端展示可节流到 1 秒 |
| 账户/持仓 | 私有 WS + REST reconcile | WS 事件驱动；每 30–60 秒或连接恢复后对账 |
| 历史 K 线 | REST 分页初始化/补缺 | 首次全量；每根 bar 收盘后增量同步 |
| 技术指标 | 本地计算 | 新 bar 完成后；新标的/历史补齐后重算 |
| 相关性 | 本地计算 | 每日收盘后或数据集更新后 |
| 宏观/公司事件 | Provider API | 每 6 小时同步；临近事件时可提高频率 |
| 新闻 | Provider API | 1–5 分钟轮询，按供应商额度和新闻量调整 |
| 策略信号 | 本地扫描器 | 每根目标周期 K 线完成后扫描；必要时单独做实时阈值监控 |
| 风险规则 | 本地计算 | 持仓/价格/止损数据变化时重算 |
| 最近活动 | 本地事件写入 | 业务事件发生时写入，不做周期性外部抓取 |
| 账户权益基准快照 | 本地任务 | 每日北京时间 00:00 保存 |
| 数据完整性检查 | 本地任务 | 每日；历史回测前强制检查 |

---

## 5. 后端需要持久化的核心数据

下列为逻辑数据模型，不强制一张表对应一个类；可以按实际 ORM 和数据库设计拆分。

| 实体 | 核心字段 | 用途 |
|---|---|---|
| `instrument` | id、venue、inst_id、inst_type、symbol、name、asset_class、base/quote/settle、ctVal、ctMult、tickSz、lotSz、minSz、state、sector | 标的主数据和合约规格 |
| `market_quote` | instrument_id、last/mark/index price、bid/ask、24h volume、source、as_of、received_at | 实时行情快照 |
| `market_candle` | instrument_id、bar、ts、open/high/low/close、volume、volume_ccy、source、is_complete | 历史行情与回测基础数据 |
| `funding_rate` | instrument_id、funding_time、funding_rate、next_funding_time、source | 永续资金费率与历史回测成本 |
| `account_snapshot` | account_id、equity、available_equity、cash_balance、unrealized_pnl、margin fields、captured_at | 账户概览与日内盈亏基准 |
| `account_ledger` | bill_id、type、currency、amount、fee、instrument_id、occurred_at、raw_payload_ref | 识别入金/出金/划转/手续费/资金费，校正账户日内权益变化 |
| `exchange_position_snapshot` | account_id、pos_id、instrument_id、pos_side、size、avg_px、mark_px、upl、lever、mgn_mode、liq_px、margin、captured_at | OKX 持仓只读快照 |
| `position_risk_config` | position_ref、stop_px、risk_budget、warning_threshold、source、updated_at | 止损和风险阈值；区分交易所止损与本地备注止损 |
| `manual_position` | id、instrument_id、side、quantity、avg_cost、stop_px、leverage、status、created_at | 手动持仓 |
| `manual_trade` | id、position_id、action、quantity、price、fee、occurred_at、note | 手动持仓操作流水 |
| `watchlist` / `watchlist_item` | list_id、instrument_id、sort_order、created_at | 自选列表及顺序 |
| `indicator_snapshot` | instrument_id、bar、ts、indicator_values、algorithm_version | 指标快照，避免每次请求全量重算 |
| `correlation_snapshot` | source_instrument、target_instrument、window、coefficient、sample_count、ts | 关联资产分析 |
| `alert_event` | id、type、severity、instrument_id、rule_id、title、detail、payload、status、dedup_key、triggered_at | 需要关注的提醒/信号事件 |
| `activity_event` | id、event_type、object_type、object_id、summary、payload、created_at | 最近活动时间线 |
| `market_event` | id、event_type、title、region、ticker、scheduled_at、actual、forecast、previous、source_url | 宏观/公司事件 |
| `news_item` | id、provider_id、title、summary、publisher、url、published_at、tickers、sentiment/tags | 新闻池和 AI 输入 |
| `strategy` / `strategy_version` | id、name、category、status、rule_json、parameters、timeframe、created_at | 策略定义与可复现版本 |
| `strategy_instrument` | strategy_version_id、instrument_id | 策略标的关联 |
| `strategy_signal` | id、strategy_version_id、instrument_id、direction、triggered_at、rule_snapshot、status | 策略产生的信号 |
| `backtest_run` | id、strategy_version_id、params_snapshot、data_version、cost_model、status、started_at、finished_at | 回测任务与复现信息 |
| `backtest_metric` | backtest_id、metrics_json | 汇总指标 |
| `backtest_equity_point` | backtest_id、ts、equity、benchmark_equity、drawdown | 曲线和回放 |
| `backtest_trade` | backtest_id、instrument_id、side、entry/exit time/price、size、fee、funding、slippage、pnl、reason | 回测交易明细 |
| `research_note` | id、type、title、content、instrument_id、strategy_id、backtest_id、created_at、updated_at | 假设/结论/决策/复盘 |
| `data_sync_job` | provider、dataset、status、started_at、finished_at、cursor、rows、error、last_success_at | 数据同步和系统健康 |
| `app_setting` | key、value、scope、updated_at | 显示偏好、风险默认值和数据源配置 |

### 每个外部数据记录建议保留的通用元数据

- `source` / `provider`
- `source_symbol` / `source_id`
- `as_of`：数据在源端代表的时间
- `received_at`：本系统收到数据的时间
- `is_delayed`：是否延迟数据
- `quality_status`：正常、缺失、延迟、异常、待验证
- `raw_payload_ref`：必要时保留原始响应或原始数据对象引用

---

## 6. 提醒、信号和活动的生成逻辑

原型里的“需要关注”“信号观察”“最近活动”都应由后端事件驱动系统提供，不应让前端根据几个字段临时拼文字。

### 6.1 提醒来源

| 来源 | 示例 | 触发逻辑 |
|---|---|---|
| 技术指标 | NVDA 跌破 MA20 | 已完成日线收盘连续 N 根低于 MA20 |
| 动量阈值 | AAPL 接近 RSI 阈值 | RSI 进入用户配置的观察区间 |
| 趋势变化 | TSLA 趋势转弱 | Close/MA20/MA60 组合状态发生变化 |
| 价格区间 | 接近支撑/阻力 | 与 20 日区间高低点的距离低于阈值 |
| 风险 | 止损距离不足 1 ATR | 通过标记价、止损价和 ATR 计算 |
| 风险 | 没有止损 | 仓位没有有效止损记录/委托 |
| 风险 | 单标的敞口过高 | 名义敞口比例超过配置阈值 |
| 策略 | 产生待确认信号 | 策略扫描命中入场/出场规则 |
| 数据 | K 线同步失败或缺口 | 数据完整性检查发现缺失/延迟 |

每条提醒需要：唯一 ID、类型、严重程度、标的、标题、解释、触发值、阈值、规则版本、触发时间、失效时间、状态（待处理/已确认/忽略/已过期）、去重键。

### 6.2 提醒去重和状态

- 同一标的、同一规则、同一 bar 不能每次扫描都生成一条新提醒。
- 状态变化需要写入活动流水。
- 规则恢复正常时，可将提醒标记为已恢复/已过期，不直接删除。
- 对于“连续 3 个交易日”这类条件，只使用已经完成的 K 线；不能用正在形成的日线提前触发确认型信号。

### 6.3 最近活动来源

- OKX 账户/持仓同步成功或失败。
- 自选新增/移除。
- 技术信号触发/恢复。
- 策略扫描产生信号、策略暂停/启用。
- 回测开始/完成/失败。
- 手动持仓创建、买入、卖出、更正。
- 研究记录创建/更新。
- 风险规则触发/解除。
- 数据源断线、重连、数据补齐。

活动记录应是事件流水，不是重新从各业务表临时拼接。首页只取最近 N 条，完整记录页可按时间和类型过滤。

---

## 7. 建议提供给前端的 API 边界

以下是建议的应用层 API，不等同于 OKX 上游 API 路径。前端只调用 trading 自己的服务端，不能直接接触 OKX 私有 API 密钥。

| API | 作用 |
|---|---|
| `GET /api/dashboard/summary` | 首页汇总：市场、账户、风险、持仓、自选摘要、提醒、策略和活动 |
| `GET /api/market/overview` | NASDAQ/S&P/DOW/VIX/BTC 市场概况 |
| `GET /api/instruments?query=` | 标的搜索和可交易列表 |
| `GET /api/watchlist` | 自选列表及指标摘要 |
| `POST /api/watchlist/items` | 添加自选 |
| `DELETE /api/watchlist/items/{id}` | 移除自选 |
| `GET /api/instruments/{id}/analysis?bar=1D` | 标的分析聚合：quote、candles、indicators、levels、correlations、events、linked strategies |
| `GET /api/positions` | OKX 与手动持仓合并视图，保留 source 类型 |
| `POST /api/manual-positions` | 创建手动持仓 |
| `POST /api/manual-positions/{id}/trades` | 写入手动买入/卖出/更正流水 |
| `GET /api/manual-positions/{id}/trades` | 手动持仓流水 |
| `GET /api/alerts` | 提醒列表和筛选 |
| `PATCH /api/alerts/{id}` | 确认/忽略提醒 |
| `GET /api/activity` | 最近活动流水 |
| `GET /api/strategies` / `POST /api/strategies` | 策略查询和创建 |
| `GET /api/strategies/{id}` / `PUT /api/strategies/{id}` | 策略详情和更新 |
| `POST /api/backtests` | 创建回测任务，返回 job/backtest ID |
| `GET /api/backtests/{id}` | 回测状态与汇总指标 |
| `GET /api/backtests/{id}/equity` | 净值/回撤序列 |
| `GET /api/backtests/{id}/trades` | 分页交易明细、筛选 |
| `GET /api/backtests/{id}/replay` | 回放数据或按时间范围取数 |
| `GET /api/research-notes` / `POST /api/research-notes` | 研究记录查询/创建 |
| `PUT /api/research-notes/{id}` / `DELETE /api/research-notes/{id}` | 研究记录更新/删除 |
| `GET /api/settings` / `PATCH /api/settings` | 用户设置 |
| `GET /api/system/health` | 系统、Provider、WebSocket、任务队列和数据质量状态 |
| `POST /api/system/sync` | 手动触发允许的同步任务 |

### WebSocket / SSE 推送事件

建议至少定义以下应用事件：

- `market.quote.updated`
- `account.snapshot.updated`
- `position.updated`
- `alert.created` / `alert.updated`
- `activity.created`
- `strategy.signal.created`
- `backtest.status.updated`
- `data_source.status.updated`

行情高频更新需要按标的订阅和前端节流；提醒、活动、回测状态等低频事件可以直接推送。

---

## 8. 可直接拆成开发 Issue 的实施顺序

以下按依赖关系安排，先把数据基础做正确，再开发依赖这些数据的页面。每一项都可以独立创建 Multica Issue。

### 阶段 A：数据基础设施

**A1. 统一标的与合约元数据**
- 实现 OKX instruments 同步。
- 建立内部 instrument ID 与 OKX `instId` 映射。
- 保存合约面值、乘数、tick、lot、最小数量、结算币种和状态。
- 验收：关注的 AAPL/NVDA/GOOG 等合约能通过 API 返回发现；不存在的合约不能被加入为可交易标的。

**A2. OKX 行情采集**
- 建立公共 WebSocket 连接、订阅管理、断线重连、REST 快照回补。
- 采集 ticker/mark/index price。
- 验收：服务端能输出 last/mark/index 三种独立价格，并显示源时间与接收时间。

**A3. K 线历史库与增量同步**
- 拉取目标合约日线历史数据，分页写入数据库。
- 支持最新 K 线增量更新、缺口扫描和补齐。
- 验收：每个标的能查询起止时间、数量、缺口数和最后更新时间；历史数据时间口径固定。

**A4. 外部市场数据 Provider**
- 先验证供应商是否提供 NASDAQ Composite/S&P 500/DOW/VIX 所需字段、频率和授权。
- 封装 Provider Adapter，避免页面绑定单一供应商格式。
- 验收：市场概览数据返回统一 schema，失败时显示陈旧/不可用状态。

### 阶段 B：核心分析与首页数据

**B1. 技术指标服务**
- 实现 MA、RSI、MACD、ATR、相对强弱、20 日高低点。
- 统一算法、精度和已完成 K 线规则。
- 验收：同一输入数据和参数可重复得到一致结果，并有单元测试。

**B2. 自选列表后端**
- 搜索、添加、移除、排序、分类筛选。
- 聚合每个标的的最新行情、指标、数据覆盖状态。
- 验收：自选增删后首页/列表/标的切换一致。

**B3. 相关性与市场环境计算**
- 实现收益率对齐、Pearson 相关系数和趋势广度。
- 配置股票/加密的默认基准与波动阈值。
- 验收：输出计算窗口、样本数、更新时间和缺数说明。

**B4. 首页市场与自选接口**
- 聚合市场、指标和数据健康状态。
- 前端不再写死价格、涨跌幅、RSI 和数据覆盖统计。
- 验收：任一数据源失效时对应模块独立降级，不把旧值显示为实时值。

### 阶段 C：账户、持仓和风险

**C1. OKX 只读账户连接**
- 服务端加密保存 API 凭据。
- 验证只读权限和账户模式。
- 实现 balance/positions REST + 私有 WS。
- 验收：浏览器不接触 Secret；页面可看到账户权益和持仓只读快照。

**C2. 手动持仓与流水**
- 实现创建持仓、买入、卖出、成本计算和流水。
- 验收：任何手动操作都可追溯；重复请求不会重复入账。

**C3. 风险计算服务**
- 实现止损距离、ATR 距离、杠杆、单标的敞口、行业敞口、保证金使用率。
- 为规则配置阈值和严重等级。
- 验收：展示的每条风险都能追溯到输入字段、计算值和触发规则。

### 阶段 D：提醒、事件和 AI 摘要

**D1. 统一事件/活动存储**
- 建立 alert_event 和 activity_event。
- 加入事件去重、状态更新和查询接口。
- 验收：首页提醒和活动均来自数据库事件，不由前端硬编码。

**D2. 宏观与公司事件同步**
- 接入宏观日历和关注标的的财报/公司事件。
- 标准化时区、标的关联、事件来源和 URL。
- 验收：可按标的和时间范围查询，事件时间明确显示北京时间。

**D3. 新闻采集与筛选**
- 按关注标的和行业获取新闻。
- 去重、保留来源 URL、发布时间和关联 ticker。
- 验收：每条 AI 摘要要点能回溯到至少一条数据/新闻来源。

**D4. AI 市场摘要**
- 输入市场指标快照、风险事件和已采集新闻。
- 生成结构化摘要：总体状态、观察要点、风险提示、引用依据、生成时间。
- 验收：无来源依据的事实不输出；数据过期时显式提示；AI 不能生成可执行订单。

### 阶段 E：策略与回测

**E1. 策略模型与规则 Schema**
- 策略定义、规则 JSON、参数版本、标的关联和状态。
- 验收：策略版本不可被历史回测引用关系覆盖。

**E2. 回测数据准备**
- K 线完整性检查。
- 资金费率历史来源验证并归档。
- 手续费和滑点模型可配置。
- 验收：启动回测前列出数据覆盖和成本缺失项；缺失时阻止或明确降级。

**E3. 回测引擎**
- 实现收盘确认、下一根 K 线成交、仓位管理、手续费、滑点、资金费。
- 输出汇总指标、权益曲线、回撤曲线和交易明细。
- 验收：固定数据、策略和参数可复现同一结果；测试无未来数据泄漏。

**E4. 回测 API、回放和导出**
- 任务状态、曲线、交易过滤、CSV 导出和历史回放。
- 验收：回放只读取已保存的回测序列，不访问实时行情。

### 阶段 F：研究记录、设置与收尾

**F1. 研究记录 CRUD 和关联**
- 假设、回测结论、决策、复盘；关联标的/策略/回测。
- 验收：筛选、创建、更新、删除和详情查看完整。

**F2. 设置与系统健康**
- 保存显示偏好、风险默认值和 Provider 配置。
- 展示同步任务、WS、数据库和历史数据健康状态。
- 验收：每个状态都有真实后端检查结果和最后成功时间。

**F3. 全站联调与演示数据清理**
- 移除前端硬编码行情、风险数值、统计数字和演示活动。
- 所有数据标记 `live / delayed / stale / demo / backtest`。
- 验收：真实数据、模拟数据、回测数据不能混排；没有数据时显示明确空态。

---

## 9. 开发前需要确认的决策

这些是影响数据模型或结果正确性的关键决策，应先于相关 Issue 确认：

1. **OKX 产品清单：**账户实际能否通过 API 查询到计划使用的美股股票永续合约？确认 AAPL/NVDA/GOOG 等具体 `instId`、合约状态和交易规格。
2. **历史 K 线覆盖：**目标合约从什么时候开始有日线？是否能覆盖首版策略回测区间？不同周期的可用深度分别是多少？
3. **外部行情 Provider：**NASDAQ Composite、S&P 500、DOW、VIX 和公司新闻/财报使用哪家供应商？要确认实时/延迟、限频、成本与个人使用授权。
4. **今日盈亏口径：**按北京时间自然日、UTC 自然日，还是美股交易日统计？首版默认可采用北京时间自然日并保存 00:00 权益快照。
5. **回测资金费率：**多年回测需要完整历史资金费率。OKX 文档当前的 funding-rate-history API 只承诺近三个月数据；决定归档方案前，不要承诺多年回测的资金费率已经精确。
6. **股票交易日与永续 24/7 数据口径：**日线策略按 OKX 24/7 合约日线，还是按美股常规交易时段构造日线？建议首版明确选 OKX 合约日线，另存底层股票参考数据。
7. **手动持仓的价格源：**手动持仓若是 OKX 已有合约则用 OKX；若是其他现货/证券资产，必须选择单独的行情源。
8. **交易执行边界：**本次开发是否继续维持只读账户 + 手动记账 + 回测，不接真实下单？本说明按 v6 原型默认不做实际下单。

---

## 10. 首版验收基线

- 所有标的均有标准化内部 ID 和真实来源 ID；不再由 UI 代码猜交易所合约。
- 实时行情、标记价格、指数价格字段分离，时间戳和来源可追踪。
- K 线具备可查询的数据覆盖、缺口和同步状态。
- 技术指标由统一计算模块生成，有算法版本和测试。
- 首页、自选、详情页的数据来自后端 API，不再依赖 HTML 中的示例常量。
- OKX 账户与持仓采用只读权限，私钥仅存服务端；有 WS 订阅和 REST 对账。
- 手动持仓具备可追溯流水。
- 所有提醒和活动均由服务端事件产生、去重、持久化。
- 回测保存策略版本、数据版本、成本参数和结果明细，可复现。
- 市场新闻/事件与 AI 摘要具备来源和时间；AI 内容不能替代真实行情字段。
- live、delayed、stale、demo、backtest 数据在 UI 和 API 层明确区分。

---

## 11. 官方资料

- [OKX API v5 文档](https://www.okx.com/docs-v5/en/)：公共行情、K 线、产品规格、账户余额、持仓、WebSocket、资金费率。
- [OKX Stock Perpetuals 产品说明](https://www.okx.com/en-us/help/stock-perpetuals)：股票永续的产品范围、交易时间和指数价格机制。说明中指出股票永续 24/7 交易，底层美股常规市场仍按交易所日历开闭市。
- [FMP API Quickstart](https://site.financialmodelingprep.com/developer/docs/quickstart)：股票行情、历史数据、指数、市场日历和新闻等数据集及 API 接入说明。

> 本文中的接口路径以官方文档当前版本为依据；实际开发前还需用目标账户、目标地区和目标合约做一次端到端验证。供应商接口权限、数据授权和历史覆盖以实际套餐及服务条款为准。
