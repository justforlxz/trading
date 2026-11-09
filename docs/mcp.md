# MCP 服务

把 P1-P3 的能力以 **Model Context Protocol**（JSON-RPC 2.0 over HTTP）暴露给外部 Agent。

本项目**不含任何 LLM**：服务器不做自然语言理解、不生成结论文字、不参与交易决策。
外部 Agent 负责推理与编排，本服务只负责鉴权、scope、受控操作与审计。
决策依据见 `docs/architecture/adr/0007-mcp-instead-of-agent.md`。

## 1. 连接与鉴权

| 项 | 值 |
| --- | --- |
| HTTP 端点 | `POST /mcp`（Streamable HTTP，支持 JSON 与 SSE 两种响应形态） |
| stdio 包装器 | `trading-mcp`（`python -m app.mcp.stdio`），只把 JSON-RPC 转发到 HTTP 端点 |
| 客户端配置 | `TRADING_MCP_URL`（默认 `http://127.0.0.1:8000/mcp`）+ `TRADING_MCP_TOKEN` |

Token 只能通过 Web「设置 → MCP 客户端」生成，**明文只在创建时返回一次**；
服务端只存 `sha256(token)`（`mcp.mcp_clients.token_hash`）。吊销后同一 token 立即 401。

```bash
# 生成客户端（scope=read 只读；scope 含 operate 才能调用操作类工具）
curl -sX POST localhost:8000/api/v1/mcp/clients \
  -H 'content-type: application/json' \
  -d '{"name": "my-agent", "scopes": ["read", "operate"]}'
# => {"client": {...}, "token": "<只出现这一次>"}

# 列表（不回显 token）与吊销
curl -s localhost:8000/api/v1/mcp/clients
curl -sX DELETE localhost:8000/api/v1/mcp/clients/1
```

鉴权失败返回 **HTTP 401 + 统一错误信封**（不是 JSON-RPC error）：

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'      # 401
```

## 2. 协议

支持的方法：`initialize`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`。

| 情形 | 行为 |
| --- | --- |
| 单请求 | 返回一个 JSON-RPC 响应对象 |
| batch（数组） | 返回响应数组；全为 notification 时 202 空体 |
| notification（无 `id`） | HTTP 202，空体；只留审计，不执行业务 |
| 未知方法 | `-32601` |
| 参数错误 | `-32602` |
| JSON 非法 | `-32700`（HTTP 400） |
| scope 不足 | **HTTP 403** + JSON-RPC error `-32003`，`data.code = "mcp_forbidden"` |
| 工具失败 | HTTP 200，`result.isError = true`，`content[0].text` 为 `{"error":{"code","message","details"}}` |

`Accept: text/event-stream` 时响应改为 SSE 帧：

```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{}}
```

```bash
TOKEN=<token>
# 初始化
curl -s localhost:8000/mcp -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'

# 工具清单
curl -s localhost:8000/mcp -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 调用工具
curl -s localhost:8000/mcp -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"get_strategy","arguments":{"strategy_id":7}}}'

# SSE 形态
curl -sN localhost:8000/mcp -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -H 'accept: text/event-stream' \
  -d '{"jsonrpc":"2.0","id":4,"method":"ping"}'
```

`tools/call` 的结果载荷统一序列化成一段 JSON 文本：

```json
{"content": [{"type": "text", "text": "{\"id\": 7, ...}"}], "isError": false}
```

## 3. scope

| scope | 能力 |
| --- | --- |
| `read` | 全部只读工具 + resources |
| `operate` | `read` 的全部能力 + 操作类工具 |

`operate` 覆盖 `read`。只读客户端调用操作类工具一律 **403**，且不产生任何业务副作用
（唯一写入是审计表 `mcp.mcp_call_log`）。

**所有操作类工具都要求非空 `reason`**：审计必须能回答「谁让它做的」。

## 4. 只读工具（scope=read）

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `market_status` | — | 执行模式、美股时段、标的数、最新确认 K 线、未解决数据问题数 |
| `list_instruments` | `limit?` `cursor?` `asset_class?` `inst_category?` `q?` | OKX 美股永续标的（含 `ct_val`/`lot_sz`） |
| `get_candles` | `inst_id` `bar` `start?` `end?` `limit?` `cursor?` | 已入库 K 线，按 `open_time` 升序 |
| `data_coverage` | `inst_id` `bar` `start?` `end?` | 应到/实到/缺口的逐日明细 |
| `list_targets` | `enabled?` `limit?` `cursor?` | 目标股票（默认只看启用中的） |
| `get_target` | `target_id` | 单个目标股票 |
| `get_relations` | `target_id` `as_of?` | 相关性快照；无快照时 `status=undefined` + 原因 |
| `get_relative_strength` | `target_id` `counterparty` `lookback?` `price_basis?` | 相对强弱（比率、动量、序列） |
| `list_opportunities` | `run_id?` `kind?` `direction?` `min_score?` `limit?` `cursor?` | 机会列表，默认最新批次，含 `reasons`/`evidence` |
| `get_opportunity` | `opportunity_id` | 机会详情（含成员） |
| `list_strategies` | `status?` `kind?` `limit?` `cursor?` | 策略列表（含策略腿） |
| `get_strategy` | `strategy_id` | 策略详情，**字段与 `GET /api/v1/strategies/{id}` 完全一致** |
| `get_backtest` | `backtest_id` | 回测运行信息与指标 |
| `risk_status` | `strategy_id?` | 是否允许增加敞口、命中限额、集中度 |
| `list_risk_events` | `kind?` `severity?` `strategy_id?` `since?` `limit?` `cursor?` | 风控事件 |
| `list_positions` | `strategy_id?` | 持仓与账户合计（标记价格估值） |
| `list_orders` | `strategy_id?` `state?` `mode?` `limit?` `cursor?` | 订单 |
| `virtual_positions` | `strategy_id?` | 策略级虚拟持仓与逐策略盈亏合计 |

`bar` 取值固定 `1m/5m/15m/1h/4h/1d`；`limit` 上限 200（`get_candles` 300）；
`Decimal` 一律以字符串返回。

## 5. 操作类工具（scope=operate）

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `trigger_scan` | `idempotency_key` `reason` `as_of?` `universe?` `params?` | 同步跑一次全市场扫描；同 `idempotency_key` 不产生第二条批次 |
| `create_strategy_draft` | `kind` `name` `templates` `reason` `target_id?` `params?` | 生成草稿（`status=draft`） |
| `update_strategy_draft` | `strategy_id` `reason` `name?` `params?` `legs?` | 仅 `draft`/`rejected` 可编辑，版本递增 |
| `submit_strategy_for_approval` | `strategy_id` `reason` | `draft → pending_approval`；**不能代替人审批** |
| `run_backtest` | `strategy_id` `window` `reason` `windows?` `bar?` `initial_capital?` `cost_model?` `criteria?` | 落库并排队，返回 `run_id`/`job_id` |
| `pause_strategy` | `strategy_id` `reason` | 仅对已获实盘授权的策略；只写 `paused_at` |
| `resume_strategy` | `strategy_id` `reason` | 同上 |
| `execute_strategy_action` | `strategy_id` `action` `reason` `inst_id` `quantity?` `side?` `position_side?` `order_type?` `price?` `idempotency_key?` | 四道闸门见下 |

### `execute_strategy_action`

`action ∈ open / increase / reduce / close / stop`，**必须带 `strategy_id` 与 `reason`**。

| action | 语义 | 方向 | `quantity` |
| --- | --- | --- | --- |
| `open` | 新开仓（`intent=entry`） | `side`/`position_side` 任一即可 | 必填 |
| `increase` | 加仓（要求已有同向持仓） | 同上 | 必填 |
| `reduce` | 部分平仓（`reduce_only`） | 与持仓相反 | 必填，且不超过持仓 |
| `close` | 全部平仓 | 与持仓相反 | 省略（必须一次平完） |
| `stop` | 止损平仓（`intent=stop`） | 与持仓相反 | 省略（必须一次平完） |

闸门顺序**固定**，任一步不通过即拒绝并写审计 `error_code`：

1. `not_live_authorized` — 策略不在 `EXECUTION_REAL_STRATEGY_IDS` 逐策略放行清单内；
2. `strategy_paused` — 策略被 `pause_strategy` 暂停；
3. `risk_blocked` / `not_approved` — 风控闸门拒绝（fail-closed）；

风控口径（与 `risk_status` 同源）：

- 策略腿的 `weight` / `notional` 允许带符号（空头为负）。校验按绝对值比较上下限，净敞口按 `side` 抵消后取绝对值，因此多空相对价值策略不会被「权重不得为负」误拒。
- 回撤闸门与 `risk_status` 使用同一份权益曲线与阈值：拒绝时 `reason` 为 `drawdown`，`breaches` 必含 `{code: drawdown_exceeded, field: drawdown, observed, threshold}`，不再出现「status 允许、执行却拒绝且 breaches 为空」。
- paper 模式下通过闸门的操作会生成模拟订单，不触达交易所（`OkxPrivateClient` 零调用）。
4. `duplicate_request` — 同 `idempotency_key` 的订单已存在。

其它稳定 `error_code`：`invalid_action`、`action_side_required`、`action_side_conflict`、
`action_position_side_required`、`action_quantity_required`、`action_quantity_mismatch`、
`exceeds_position`、`no_position`、`instrument_not_found`、`strategy_not_found`。

模拟/实盘隔离沿用 S10：`REAL_TRADING_ENABLED=false`（默认）时执行落在 paper，
不触碰 OKX 真实接口；实盘仍需三个开关同时打开。

```bash
curl -s localhost:8000/mcp -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{
        "name":"execute_strategy_action",
        "arguments":{"strategy_id":7,"action":"open","reason":"外部 agent 按信号开多",
                     "inst_id":"AAPL-USDT-SWAP","side":"buy","quantity":"1",
                     "idempotency_key":"agent-0001"}}}'
```

## 6. 硬边界（架构性，不靠判断）

工具清单里**不存在**这些能力，因此外部 Agent 无法通过 MCP 取得它们：

- `place_order` —— 没有裸下单入口；所有订单必须归属某个策略；
- `approve_strategy` / `live_authorize` / `set_risk_limit` / `toggle_live_trading`
  —— 授权类动作只能由人在 Web 上完成。

`tests/mcp/test_tools_consistency.py::test_ac5_tool_list_excludes_authorization_and_naked_order_tools`
对 `tools/list` 做负向断言。

## 7. resources

| URI | 内容 |
| --- | --- |
| `market://snapshot` | 全市场最新特征截面（扫描产物，含广度与交易时段） |
| `strategy://{id}` | 单条策略详情（与 Web 详情一致） |
| `backtest://{id}` | 回测运行信息与指标 |

```bash
curl -s localhost:8000/mcp -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":5,"method":"resources/read","params":{"uri":"strategy://7"}}'
# => {"result":{"contents":[{"uri":"strategy://7","mimeType":"application/json","text":"{...}"}]}}
```

## 8. 审计

每次调用写一条 `mcp.mcp_call_log`：`client_id`、`tool`、`args_digest`（sha256，不落明文）、
`status`（`ok`/`error`/`denied`）、`error_code`、`reason`、`latency_ms`、`created_at`。

```sql
-- 某客户端最近的操作类调用
SELECT tool, status, error_code, reason, latency_ms, created_at
FROM mcp.mcp_call_log
WHERE client_id = 1 AND tool IN (
  'trigger_scan','create_strategy_draft','update_strategy_draft',
  'submit_strategy_for_approval','run_backtest',
  'pause_strategy','resume_strategy','execute_strategy_action')
ORDER BY id DESC LIMIT 50;
```

## 9. stdio 包装器

```bash
export TRADING_MCP_URL=http://127.0.0.1:8000/mcp
export TRADING_MCP_TOKEN=<token>
trading-mcp          # 每行一条 JSON-RPC，逐行转发并把响应写回 stdout
```

只转发，不在本地复算业务：没有缓存、没有兜底数据、不改写结果。
`TRADING_MCP_TOKEN` 缺失时退出码 2。

## 10. 已知取舍

- `pause_strategy` / `resume_strategy` 用 `strategy.strategy.paused_at`（迁移 0009 新增）
  表达运行暂停，**没有新增策略状态**：`status` 仍是
  `draft/pending_approval/approved/rejected/archived` 五值。
  该列不出现在 Web API 响应里，因此 `get_strategy` 与 Web 详情仍逐字段一致；
  暂停状态通过 `execute_strategy_action` 的 `strategy_paused` 拒绝可见。
- `trigger_scan` 在请求内同步执行扫描（外部 Agent 需要立即看到结果），
  不动 arq 的 `scan_opportunities` 任务；两者共用 `opportunity.run_key` 幂等口径。
