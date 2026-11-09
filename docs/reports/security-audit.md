# 安全审计（MKACG-703 / S12-04）

**结论：1.0 发布前的安全红线全部满足。** 仓库内无硬编码密钥与私钥（两条扫描均 0 命中）；运行期容器内 OKX
凭据长度均为 0、`REAL_TRADING_ENABLED=False`，日志里既不出现 MCP 明文令牌也不出现 OKX 密钥；MCP 令牌鉴权的
三种失败态（无令牌 / 错误令牌 / 已吊销令牌）一律 401，只读令牌调用操作工具一律 403 且**不产生任何业务写入**；
未经授权的真实下单在任何请求体下都是 403，`execution.order` 中 `mode='real'` 的记录数为 **0**。
本轮审计**没有提交任何真实订单、没有动用任何资金**，全部探测为只读查询加一次被拒绝的越权尝试。

文档层面的三处不一致（api-contract 缺 MCP 章节、data-model 缺 mcp schema 与 `strategy.paused_at`、
`docs/plan/p2-p4.md` 仍保留作废的 AI 计划表）已在本轮**全部修正**，见第 5 节。

## 1. 范围与口径

| 项 | 值 |
| --- | --- |
| 审计日期 | 2026-11-10（UTC+8） |
| 代码基线 | `master@7dfe8cd`（S11 合并后）+ 本轮 S12 集成验收改动 |
| 运行形态 | Docker Compose 六服务（`postgres`/`redis`/`api`/`worker`/`scheduler`/`web`），单机 |
| 数据库版本 | `0009_mcp_schema (head)` |
| 交易状态 | `GET /execution/mode` → `mode=paper`、`real_trading_enabled=false`、`credentials_configured=false` |
| 复现方式 | `bash scripts/e2e/security_audit.sh`（只读 + 一次被拒的越权调用），输出落 `$HOME/.cache/s12/security.out`；**逐项断言，全部通过才退出 0，任一不符退出 1** |
| 未覆盖 | 外部渗透测试、TLS/网关、多实例与跨租户隔离、速率限制压测（见第 6 节） |

### 1.1 脚本的断言与安全门禁

本报告的结论不是「人工看了一眼输出」，而是脚本断言的结果。脚本分两层保护：

1. **姿态前置门禁（P 段）**：开跑先 `GET /api/v1/execution/mode`，要求 `mode=paper` 且
   `real_trading_enabled=false`；不满足就立即以退出码 1 中止，**在此之前不发送任何下单请求**。
   B 组（真实交易门禁）下单前再复核一次，防止巡检途中有人打开实盘开关。
2. **逐项断言**：每条检查都有期望值，不符即打印 `FAIL: …` 并在结尾以退出码 1 结束，使
   「退出 0」重新成为可用的验收判据。断言覆盖：

| 断言 | 期望 |
| --- | --- |
| A1 / A2 / A6 | 401 且 `error.code=mcp_unauthorized` |
| A3 | 200 且 `result.isError≠true`，返回的策略名非空 |
| A4 | 403、JSON-RPC `-32003`、`error.data.code=mcp_forbidden`；`strategy.strategy` 与 `scan_opportunities` 任务数不变；`mcp_call_log` 恰好 +1 且该行为 `denied/mcp_forbidden` |
| 令牌存储 | `token_hash` 为 64 位十六进制；以明文令牌为条件查询命中 0 行 |
| A5 | 200 且 `revoked_at` 非空 |
| B1 | 200、`mode=paper`、`real_trading_enabled=false` |
| B2 / B3 | 403 且 `error.code=real_trading_disabled` |
| B4 / B5 | `mode='real'` 订单数 0；订单 mode 只有 `paper` |
| C1 / C2 | 容器内三项凭据长度均 0；`REAL_TRADING_ENABLED=False` |
| C3 / C4 | 明文令牌在 api 日志中 0 次；OKX 密钥值在 api/worker 日志中 0 次 |

**门禁负向验证**（证明它真的会拦住实盘态）：用一个只回 `{"mode":"real","real_trading_enabled":true}`
的桩服务冒充 API，把 `API_ROOT` 指过去再执行脚本：

```text
$ OUT=... API_ROOT=http://127.0.0.1:8097 bash scripts/e2e/security_audit.sh
=== P. 投产姿态前置门禁 ===
  ok   GET /execution/mode HTTP = 200
FAIL: execution.mode 期望 [paper] 实际 [real]
FAIL: real_trading_enabled 期望 [false] 实际 [true]
致命：当前部署不是 paper + REAL_TRADING_ENABLED=false。
本脚本后面会请求 POST /execution/orders（真实下单端点）以验证 403 门禁；
在实盘态执行会真的向交易所下单，因此已在此中止，未发送任何下单请求。
（退出码 1）

$ cat $HOME/.cache/s12/realmode.hits      # 桩服务收到的全部请求
GET /api/v1/execution/mode
```

桩服务只收到 1 个 GET，**没有任何 `POST /execution/orders`**——即「在实盘态运行本脚本会真的下单」
这条路径已被门禁关闭。

审计项按四组组织，下文逐项给出「命令 → 原始输出 → 结论」。

| 组 | 主题 | 项 |
| --- | --- | --- |
| A | MCP 令牌鉴权与越权 | A1–A6 |
| B | 真实交易门禁 | B1–B5 |
| C | 凭据与配置面 | C1–C4 |
| D | 文档一致性 | D1–D3 |

## 2. 密钥与凭据面

### 2.1 代码库硬编码扫描

```bash
$ rg -n 'api_key\s*=\s*"[A-Za-z0-9]|secret\s*=\s*"[A-Za-z0-9]' backend scripts
（无输出，退出码 1）

$ git grep -nE '(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9]{20,})' -- .
（无输出，退出码 1）
```

**结论：0 命中。** 代码与脚本里没有硬编码的 api key、secret、AWS access key、PEM 私钥或 `sk-` 形式的模型密钥。

### 2.2 配置与环境变量面

```bash
$ rg -n 'OKX|REAL_TRADING_ENABLED' infra/.env.example
23:OKX_REST_BASE_URL=https://www.okx.com
30:REAL_TRADING_ENABLED=false
31:# OKX 私有接口凭据（只从这里注入，绝不写进代码）。留空即无法真实下单。
32:OKX_API_KEY=
33:OKX_API_SECRET=
34:OKX_API_PASSPHRASE=
```

`infra/docker-compose.yml` 的 `x-backend-env` 同样以 `${OKX_API_KEY:-}` 形式透传，缺省为空串；
`REAL_TRADING_ENABLED: ${REAL_TRADING_ENABLED:-false}`。**结论：凭据只有环境变量这一个入口，缺省为空，
默认状态下系统连真实下单的凭据都没有。**

### 2.3 运行期凭据（C1–C2）

```text
C1 容器内 OKX 凭据长度: api_key 0 secret 0 passphrase 0
C2 REAL_TRADING_ENABLED: False
```

**结论：** 运行中的 api 容器内三项凭据长度均为 0，实盘开关为 `False`——即使绕过接口校验，也没有可用凭据签名。

### 2.4 日志面（C3–C4）

```text
C3 明文令牌出现在 api 日志中的次数: 0
C4 OKX 密钥值出现在 api/worker 日志中的次数: 0
```

C3 用本次新建客户端的完整明文令牌在 `docker compose logs api` 中做全文匹配，C4 用 `okx_api_secret=` 前缀匹配。
**结论：令牌只在创建响应里出现一次，不落日志；凭据值即使被误配也不会被打进日志。**

### 2.5 令牌存储形态（A 组前置事实）

```text
client_id=2 token_len=43 token_prefix=wA5c...
token_hash in db: 64 位十六进制摘要（此处不复制具体值）
plaintext token in db: 0
```

`mcp.mcp_clients` 只存 `sha256(明文)` 的 64 位十六进制摘要（`UNIQUE(token_hash)`），表结构中没有明文字段：
以明文令牌做条件查询命中 **0** 行。**结论：数据库泄露不等于令牌泄露；令牌无法从库中还原。**

## 3. MCP 鉴权与越权（A1–A6）

| 项 | 场景 | 期望 | 实测 | 结论 |
| --- | --- | --- | --- | --- |
| A1 | 不带 `Authorization` 调 `tools/call` | 401 | 401 `mcp_unauthorized` / `missing bearer token` | ✅ |
| A2 | 携带一个未签发的随机令牌 | 401 | 401 `mcp_unauthorized` / `unknown or revoked token` | ✅ |
| A3 | 携带刚签发的只读令牌调 `get_strategy` | 200 | 200 | ✅ |
| A4 | 只读令牌调操作工具 `trigger_scan` | 403 且无业务写入 | 403 `-32003 mcp_forbidden`（`scope=operate`）；`strategy.strategy` 1→1、`scan_opportunities` 任务 2→2、仅 `mcp_call_log` 4→5 | ✅ |
| A5 | `DELETE /api/v1/mcp/clients/{id}` 吊销 | 200 且 `revoked=true` | 200 `"revoked":true`，`revoked_at` 已写 | ✅ |
| A6 | 吊销后用同一令牌再调 | 401 | 401 `unknown or revoked token` | ✅ |

原始输出：

```text
A1 无令牌 -> 401  {"error":{"code":"mcp_unauthorized","message":"missing bearer token","details":{},"request_id":"..."}}
A2 错误令牌 -> 401  {"error":{"code":"mcp_unauthorized","message":"unknown or revoked token","details":{},"request_id":"..."}}
A3 正确令牌 -> 200
A4 read 令牌调 operate 工具 -> 403  {"jsonrpc":"2.0","id":2,"error":{"code":-32003,"message":"client 's12-security-audit' lacks scope operate","data":{"code":"mcp_forbidden","scope":"operate","scopes":["read"]}}}
A4 越权前后：strategy.strategy 1 -> 1；scan_opportunities 任务 2 -> 2；mcp_call_log 4 -> 5
A4 审计行标记被拒 = denied/mcp_forbidden
A5 吊销客户端 -> 200  {"id":2,...,"revoked_at":"2026-11-09T19:19:59.787333Z","revoked":true}
A6 吊销后同令牌 -> 401  {"error":{"code":"mcp_unauthorized","message":"unknown or revoked token",...}}
```

**结论：** 鉴权失败是 HTTP 401 + 平台错误信封（不是 JSON-RPC 错误），作用域不足是 HTTP 403 + JSON-RPC
`-32003`；越权尝试只留审计痕迹（`mcp_call_log` +1），**业务表零变化**，不存在「先执行再拒绝」的窗口。
吊销即时生效，无需等待缓存过期。

## 4. 真实交易门禁（B1–B5）

| 项 | 场景 | 期望 | 实测 | 结论 |
| --- | --- | --- | --- | --- |
| B1 | `GET /api/v1/execution/mode` | `paper` + 实盘关闭 | 200 `{mode:paper, real_trading_enabled:false, credentials_configured:false, reason:real_trading_disabled}` | ✅ |
| B2 | 空请求体 `POST /execution/orders` | 403（门禁先于校验） | 403 `real_trading_disabled` | ✅ |
| B3 | 完整合法请求体 `POST /execution/orders` | 403 | 403 `real_trading_disabled` | ✅ |
| B4 | `select count(*) from execution."order" where mode='real'` | 0 | 0 | ✅ |
| B5 | 订单 mode 分布 | 只有 paper | `paper\|1` | ✅ |

```text
B1 GET /execution/mode -> 200  {"mode":"paper","real_trading_enabled":false,"credentials_configured":false,"real_strategy_ids":[],"paper_fill_chunks":["0.5","0.5"],"stop_loss_ratio":"0.05","reason":"real_trading_disabled"}
B2 空请求体 POST /execution/orders -> 403  {"error":{"code":"real_trading_disabled","message":"真实交易未开启 (REAL_TRADING_ENABLED 缺省为 false)",...}}
B3 完整请求体 POST /execution/orders -> 403  {"error":{"code":"real_trading_disabled","message":"真实交易未开启 (REAL_TRADING_ENABLED 缺省为 false)",...}}
B4 mode=real 订单数: 0
B5 全部订单按 mode 分布: paper|1
```

**结论：** 实盘门禁在请求体校验之前生效（空体也是 403，说明它不依赖参数合法性），且 1.0 全流程只产生
`mode=paper` 的订单。**本轮没有下过任何真实订单，也没有触碰任何真实资金。**

## 5. 文档一致性（D1–D3）

三处不一致全部**已修**（不是登记债）。

| 项 | 问题 | 处理 | 证据 |
| --- | --- | --- | --- |
| D1 | `docs/architecture/api-contract.md` 只写到 §3.9 执行域，S11 交付的 MCP 接口没有契约章节 | **已修**：新增 `### 3.10 MCP`，覆盖 `POST /mcp`（Streamable HTTP + SSE）、bearer 鉴权、401 `mcp_unauthorized`、方法集、批量/通知语义、403 `-32003 mcp_forbidden`、工具失败 `isError`（HTTP 200）、`mcp_call_log` 审计，以及 `POST/GET /api/v1/mcp/clients`、`DELETE /api/v1/mcp/clients/{id}`；18 个只读工具与 8 个操作工具逐个列出 | `rg -n '^### 3\.10' docs/architecture/api-contract.md` → `393:### 3.10 MCP` |
| D2 | `docs/architecture/data-model.md` 无 mcp schema，`strategy.paused_at` 与迁移 `0009_mcp_schema` 未记录 | **已修**：schema 清单补 `risk`/`execution`/`mcp`；`strategy.strategy` 字段表补 `paused_at`（含暂停语义）；新增 `## 10. mcp schema（S11 MCP 服务）` 记录 `mcp_clients`/`mcp_call_log` 全部列与索引；补完整迁移链表 0001→0009 | `rg -n '^## 10\. mcp|0009_mcp_schema' docs/architecture/data-model.md` → `324:## 10. mcp schema…`、`356:| 0009_mcp_schema | …` |
| D3 | `docs/plan/p2-p4.md` §3 仍列着已被 ADR-0007 取代的 P4-01~P4-07「AI Agent」计划表，容易被误读为待办 | **已修**：表前加醒目引用块声明「历史计划，已作废、不实施」，点名 `backend/app/ai/**`、`/ai/*`、`scripts/e2e/p4_smoke.sh`、`docs/reports/p4-acceptance.md` 在本仓库**不存在**；表后加斜体说明指向实际交付与验收；S11 出口门禁的 `rg` 目标从 `backend/app/ai` 改为 `backend/app/mcp` | `sed -n '66,80p' docs/plan/p2-p4.md` |

D3 的门禁命令实测（MCP 不提供裸下单工具，只命中一条说明性注释）：

```bash
$ rg -n 'place_order|cancel_order|create_order' backend/app/mcp
backend/app/mcp/tools.py:9:* 裸下单(`place_order`)——所有订单必须归属某个策略;
```

## 6. 未覆盖与工程债

| 项 | 说明 |
| --- | --- |
| 未做外部渗透测试 | 本轮是「配置 + 接口 + 数据库」的自证式审计，没有第三方渗透；结论只覆盖上述 A/B/C/D 项 |
| 未做 TLS / 反向代理 | 交付形态是单机 Compose 直连 8000/5173 端口，生产化必须由网关终结 TLS（属部署侧，见 `docs/runbook.md`） |
| 未做速率限制压测 | `POST /mcp` 只有作用域校验，没有限流；令牌泄露后的滥用面靠「吊销」而非限流控制 |
| MCP 客户端必须手工轮换 | 令牌只在创建时返回一次，轮换即「吊销 + 新建」，无自动过期；`full_smoke.sh` 每跑一次就轮换一次（`mcp_clients` 行数会增长） |
| 多实例/跨租户 | 单实例单账户假设；K8s 形态未交付（详见 `docs/reports/release-1.0.md` 的工程债清单） |
