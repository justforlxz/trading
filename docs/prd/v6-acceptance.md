# trading v6 真实功能验收清单与执行规则

> 对应节点：S7-2（MKACG-826）
> 适用范围：v6 全部任务完成，且 S7-1 与 S7-2 合并后执行的真实功能验收
> 清单基线：`docs/prd/v6.md`，基线提交 `1a55889`
> 验收对象：验收唤醒时的 `master` 提交，或任务明确指定的 PR head；报告必须写明实际提交

本文只定义验收清单和执行规则，不执行验收，不修改代码，不创建修复 issue。验收由 Mika 以 lxz 的副手身份执行，结论以真实页面、真实接口、真实数据库和真实推送为依据，不以代码阅读或自动化测试代替功能验收。

## 1. 验收环境

### 1.1 前置条件

- 仓库根目录已经完成 `pnpm --dir frontend install`；后端虚拟环境 `.venv` 可用。
- 本机已安装 `podman`、Python 3.12 及以上、Node.js 20 及以上、`pnpm`、`curl`、`jq`。
- 可以访问 OKX 公共行情与模拟盘接口；不能访问时按 `BLOCKED` 记录，不用 fixture 或演示数据替代。
- OKX 只使用模拟盘，只调用只读接口；验收期间不执行真实下单、撤单、改单、平仓、资金划转和提现。

### 1.2 使用独立 schema

验收数据库只使用独立 schema `v6_accept`，不得复用开发库的 `public`，也不得复用其他任务留下的 schema。每次验收开始时重新创建，结束时删除。

```bash
export DATABASE_URL="postgresql+psycopg://trading:trading@127.0.0.1:5432/trading"
export DATABASE_SCHEMA="v6_accept"
export APP_ENV="dev"
export OKX_DEMO=1

make db-up

podman exec trading-db psql -U trading -d trading -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA IF EXISTS v6_accept CASCADE' \
  -c 'CREATE SCHEMA v6_accept'

cd backend
../.venv/bin/python -m alembic upgrade head
cd ..
```

执行后确认迁移版本、表数量和 schema 名称：

```bash
podman exec trading-db psql -U trading -d trading -Atc \
  "select version_num from v6_accept.alembic_version"
podman exec trading-db psql -U trading -d trading -Atc \
  "select count(*) from information_schema.tables where table_schema = 'v6_accept'"
```

预期：迁移版本为当前仓库的唯一头版本（基线为 `0018`），表数量大于 0，且查询只在 `v6_accept` 中看到表。若 `DATABASE_SCHEMA` 为空、迁移写入 `public`、或 `v6_accept` 不是新建 schema，立即停止验收并记为 `BLOCKED`。

### 1.3 OKX 凭据

凭据优先从环境变量读取；环境变量缺失时，从本机 `~/.okx/config.toml` 的 `[profiles.okx-demo]` 读取。只允许模拟盘，`OKX_DEMO` 必须为 `1`。不得把密钥写入仓库、`.env`、命令行参数、验收报告或日志，不得使用 `set -x`、`env`、`printenv` 等会回显密钥的命令。

```bash
export OKX_DEMO=1

if [ -z "${OKX_API_KEY:-}" ] || [ -z "${OKX_SECRET_KEY:-}" ] || [ -z "${OKX_PASSPHRASE:-}" ]; then
  eval "$(python3 - <<'PY'
import os
import shlex
import tomllib

path = os.path.expanduser("~/.okx/config.toml")
profile = {}
try:
    with open(path, "rb") as handle:
        profile = tomllib.load(handle).get("profiles", {}).get("okx-demo", {})
except FileNotFoundError:
    profile = {}

fields = {
    "OKX_API_KEY": ("api_key", "apiKey"),
    "OKX_SECRET_KEY": ("secret_key", "secretKey"),
    "OKX_PASSPHRASE": ("passphrase",),
}
for env_name, names in fields.items():
    if os.environ.get(env_name):
        continue
    for name in names:
        value = profile.get(name)
        if value:
            print(f"export {env_name}={shlex.quote(str(value))}")
            break
PY
)"
fi

: "${OKX_API_KEY:?缺少 OKX_API_KEY}"
: "${OKX_SECRET_KEY:?缺少 OKX_SECRET_KEY}"
: "${OKX_PASSPHRASE:?缺少 OKX_PASSPHRASE}"
test "${OKX_DEMO}" = "1"
```

验收开始前确认数据库里没有保存过 API Key。`apply_saved_settings()` 会在启动时用 `settings.okx_api_key` 覆盖环境变量；该字段非空会让环境变量凭据失效，也会让私有接口返回 401。

```bash
podman exec trading-db psql -U trading -d trading -Atc \
  "select count(*) from v6_accept.settings where coalesce(okx_api_key, '') <> ''"
```

预期为 `0`。验收期间不通过 `PATCH /api/settings` 写入真实 API Key；只验证页面和接口不会回显明文。若必须演示写入行为，只能使用一次性占位字符串，并在演示后清空 `v6_accept.settings.okx_api_key`、重启后端，再恢复环境变量凭据。

### 1.4 启动后端和前端

后端按真实进程启动，绑定 `0.0.0.0:8000`：

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
```

另开终端构建并启动前端。当前 `backend/app/main.py` 没有挂载 `frontend/dist`，界面由 Vite 预览进程提供，`/api` 反向代理到 `127.0.0.1:8000`：

```bash
pnpm --dir frontend build
VITE_API_TARGET=http://127.0.0.1:8000 \
  pnpm --dir frontend preview --host 0.0.0.0 --port 5173
```

如果验收时的提交已经把前端静态产物挂到同一个 uvicorn 进程，改用该提交的实际启动方式，并在报告中写明启动命令和提交。无论哪种方式，都必须先执行 `pnpm --dir frontend build`。

检查后端存活和前端构建产物中没有开发用假后端：

```bash
curl -fsS http://127.0.0.1:8000/api/health
rg -l "setupWorker|dev-backend|Mock Service Worker" frontend/dist
```

预期：健康检查返回 `status=ok`；`rg` 无输出。若 `rg` 有输出，说明生产构建包含开发用假后端，记为 `FAIL`。

### 1.5 验收前基线检查

新 schema 刚迁移完时，下列查询都应为 `0`。任何非 `0` 都说明 schema 被旧数据污染，停止验收并在报告中写明污染表和行数。

```bash
podman exec trading-db psql -U trading -d trading -P pager=off -c "
select 'account_snapshots' as table_name, count(*) from v6_accept.account_snapshots where raw_payload_ref = 'fixture'
union all
select 'exchange_position_snapshots', count(*) from v6_accept.exchange_position_snapshots where raw_payload_ref = 'fixture'
union all
select 'manual_positions', count(*) from v6_accept.manual_positions where note like 'fixture%'
union all
select 'strategies', count(*) from v6_accept.strategies where name like '%走查策略%' or name like '%验证策略%'
union all
select 'settings', count(*) from v6_accept.settings where coalesce(okx_api_key, '') <> ''
"
```

真实 OKX 模拟盘只读接口写入的账户快照和持仓快照可以保留，但必须能追溯 `source=okx_rest` 与本次验收时间。`raw_payload_ref=fixture`、`source=fake`、备注以 `fixture` 开头的数据一律不能作为通过证据。

### 1.6 验收后清理

报告发布后停止前端预览进程和后端 uvicorn 进程，然后删除验收 schema。只删除 `v6_accept`，不得删除 `public`、其他 schema、数据库容器或容器数据卷。

```bash
podman exec trading-db psql -U trading -d trading -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA IF EXISTS v6_accept CASCADE'
```

## 2. 功能点清单

### 2.1 清单范围和编号

清单以 `docs/prd/v6.md` 的 3.1、3.2、3.3 三张表为准，覆盖其中前端或后端状态为 `已实现` 或 `开发中` 的全部功能行。共 95 行：

- 3.1 页面与页面区块：61 行，对应 60 个页面功能点。
- 3.2 规格第 7 节 API：29 行，对应 17 个接口功能点。
- 3.3 保留但不通过 v6 页面暴露的能力：5 行，对应 5 个后端回归点。

数据推送另设 1 个页面级功能点 `I-01`，与接口功能点 `P-17` 从页面和接口两侧验证同一行。按需同步另设 5 个功能点 `S-01` 至 `S-05`，见 2.13。清单共 88 个功能点。报告中的“功能点总数”按 88 计算，并同时报告 PRD 行覆盖率 `95/95`。MKACG-853 与 MKACG-857 分别删除了「近期事件」和「合约元数据」页面行，本清单同步删除对应功能点。`未实现` 和 `不适用` 行不在本次功能验收范围内；如果验收时 `docs/prd/v6.md` 的状态已变化，以验收唤醒时的文档为准，并在报告中记录差异。

证据类型统一记为：

- `E1` 页面证据：URL、视口宽度、操作时间、截图；截图中必须能看到页面标题或地址栏。截图只作补充，关键数值必须能用 `E2` 或 `E3` 复核。
- `E2` 接口证据：完整 `curl` 命令、HTTP 状态码、相关 JSON 字段；包含 `as_of`、`source`、`status` 等时间与来源字段。
- `E3` 数据库证据：`psql` 查询语句与结果。
- `E4` 命令证据：构建、静态检查或测试命令、退出码和关键输出。
- `E5` 推送证据：浏览器 DevTools 的 WebSocket 帧记录，或 `websocat` 等客户端记录的帧；必须包含接收时间与事件 JSON。
- `E6` 写入证据：写入后的数据库行、流水、幂等键或活动事件。

### 2.2 外壳

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| A-01 | 3.1 外壳 / 6 项主导航；标的详情不单独进入导航 | `/`、`/watchlist`、`/positions`、`/strategies`、`/journal`、`/settings`、`/watchlist/<instId>` | 在 1440px 宽度依次打开六个路径；再直接打开一个标的详情 URL；刷新页面 | 侧栏只有六项，顺序为概览、自选、持仓、策略与回测、记录、设置；当前项高亮；标的详情不出现独立导航项；直接打开详情不跳回首页 | E1 |
| A-02 | 3.1 外壳 / 响应式侧栏抽屉 | `/` 及任一页面 | 把视口调到 1080px 以下，打开菜单；分别用遮罩、Esc、点击导航项关闭；再把视口调到 390px 检查横向滚动 | 抽屉可打开和关闭；三种关闭方式都有效；390px 页面没有整体横向溢出，表格可横向滚动或按列隐藏 | E1 |
| A-03 | 3.1 外壳 / 顶栏显示当前区块名、真实数据连接状态和主题切换 | 六个主导航页面 | 逐个切换导航；在 DevTools 把网络设为 Offline，等待连接状态变化；切回 Online；切换浅色和深色主题并刷新 | 顶栏显示当前区块名；连接状态来自真实健康检查，未知时显示“未连接”而不是固定“正常”；主题切换生效并在刷新后保留 | E1 |
| A-04 | 3.1 外壳 / 统一页面标题组件支持 eyebrow、title、description、actions | 六个主导航页面 | 逐个查看页面标题区域；有 actions 的页面检查按钮位置和可点击性 | 标题结构一致，包含 eyebrow、title、description；有 actions 时按钮位于标题区域且不遮挡正文 | E1 |
| A-05 | 3.1 外壳 / 持仓页骨架 `/positions`；记录页骨架 `/journal` | `/positions`、`/journal` | 直接打开两个路径并刷新 | 两个路径都能打开，页面标题正确，不出现 404；页面内容由后续功能点 B、E、G 分别验证 | E1 |

### 2.3 概览

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| B-01 | 3.1 概览 / 账户概览 | `/` | 打开首页账户卡；与 `GET /api/account/summary` 对比数值；检查来源和数据时间；断开 OKX 凭据后刷新 | 显示权益、今日盈亏、可用与已用保证金、未实现盈亏、保证金使用率；每项有来源和数据时间；名义价值后端未提供时不显示或明确写“未提供”，不显示 0 冒充；凭据缺失时显示明确状态 | E1、E2 |
| B-02 | 3.1 概览 / 风险监控 | `/` | 打开首页风险卡；与 `GET /api/risk/exposure` 或 `GET /api/dashboard/summary` 的 `risk` 模块对比 | 显示综合等级、临近止损数、高杠杆数、单标的敞口、未设置止损数、保证金使用率；口径字段随数值显示；没有规则数据时显示空态或原因，不编造数字 | E1、E2 |
| B-03 | 3.1 概览 / 当前持仓：OKX 与手动持仓合并视图，保留来源 | `/` | 打开首页持仓表；与 `/api/positions/exchange`、`/api/manual-positions` 对比；检查来源列和止损距离字段 | 两种来源合并显示并保留 `exchange` 或 `manual` 来源；最多显示五行；`stop_distance_pct` 为空时写“后端未返回止损距离”，不写成“未设置止损”；刷新后条目一致 | E1、E2、E3 |
| B-04 | 3.1 概览 / 市场概况：BTC | `/` | 打开市场概况卡；核对数值、涨跌、市场时段、来源、报价时间、状态；与 `GET /api/market/overview` 对比 | 只有 `symbol=BTC` 一项（行情取 OKX 公共 ticker 的 `instId=BTC-USDT`）；数值非空；`source=okx_spot`；`quality_status` 为 `normal` 或如实 `stale`；不出现 NASDAQ、S&P 500、DOW、VIX 占位项；报价过期时显示 `stale` 和可读原因 | E1、E2 |
| B-05 | 3.1 概览 / 市场摘要：带来源和生成时间的 AI 归纳 | `/` | 打开市场摘要卡；检查总体结论、观察要点、风险、免责声明、生成时间、数据截止时间；点击每条事实的来源链接 | 每个事实点至少一条来源；没有来源的句子不显示；来源只能回到市场概况、提醒与风险区块，不出现新闻来源；数据陈旧时显示提示和“数据不完整” | E1、E2 |
| B-06 | 3.1 概览 / 关注列表摘要：价格、日涨跌、RSI、趋势、信号 | `/` | 打开关注列表卡；与 `GET /api/watchlist` 和推送帧对比；检查价格时间与快照时间标注 | 显示总数、偏多/偏空数、覆盖率与最多五行；价格按推送事件时间更新；日涨跌、RSI、趋势显示 HTTP 快照时间；后端没有信号时不拼信号文案 | E1、E2、E5 |
| B-07 | 3.1 概览 / 提醒与活动：待处理提醒、最近活动 | `/` | 打开提醒卡和活动卡；对待处理提醒执行确认和忽略；刷新；检查活动列表 | 提醒来自 `alert_events`，状态变化写入活动；活动来自 `activity_events`，不由前端硬编码；重复处置返回冲突或明确提示，不重复写活动 | E1、E2、E3、E6 |
| B-08 | 3.1 概览 / 策略运行：策略总数、启用数、运行状态、待确认信号、近 30 日回测表现 | `/` | 打开策略运行卡；与 `GET /api/dashboard/summary` 的 `strategies` 模块对比 | 显示总数、已启用、运行中、待确认信号和近 30 天回测；最近回测显示收益、最大回撤、交易次数和窗口；没有记录时显示“最近没有回测记录”，不编造 | E1、E2 |
| B-09 | 3.1 概览 / 最近活动时间线 | `/` | 打开最近活动时间线；检查事件类型、对象、时间顺序；与 `GET /api/activity` 对比 | 按时间倒序显示；每条有事件类型、对象和北京时间；来源为数据库事件表，不显示前端拼出的假事件 | E1、E2、E3 |

### 2.4 自选

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| C-01 | 3.1 自选 / 搜索、加入自选、移出自选、切换分组 | `/watchlist` | 搜索一个真实标的并加入自选（加入时在表单里选一个分组）；加入一个尚未同步日线的标的；加入一个只有 1 根日线的标的；用列表上方的分组筛选行切到另一个分组再切回；在行尾菜单里把标的移到另一个分组；移出自选；刷新页面 | 搜索只调用 `GET /api/instruments/search`，不产生 `data_sync_jobs` 记录；加入后列表和首页关注列表同步，并触发该标的 1d 日线后台同步；没有日线的标的仍返回 201 并显示「尚未同步」，页面不报错；只有 1 根日线的标的显示最新价和「未生成」、涨跌幅为空；移出后消失；加入时选的分组与行尾菜单写入的分组都能在 `GET /api/watchlist` 里读回；分组筛选同时影响列表与关注汇总；重复加入不产生重复行 | E1、E2、E3、E6 |
| C-02 | 3.1 自选 / v6 列表列：标的、24H 分时、价格 / 涨跌、信号 | `/watchlist` | 打开自选列表；逐列核对标的、24H 分时、价格 / 涨跌、信号；再打开标的详情页核对指标卡与数据覆盖表，并核对关注汇总 | 列表只有 4 列，不得出现 RSI(14)、ATR(14)%、K 线覆盖、最近更新时间列；这些数值在详情页的指标卡与「数据覆盖」表各自有值或明确缺值说明；列表数值来自 `GET /api/watchlist`，不在前端重新计算；价格按推送更新 | E1、E2 |
| C-03 | 3.1 自选 / 分组筛选：全部 + 各分组 | `/watchlist` | 依次选择全部与每一个分组；记录每个分组的数量与标的 | 每个分组只含该分组标的；全部等于各分组之和；没有匹配时显示空态「当前分组下没有标的」，不把其他分组混入；页面不出现「股票永续」「加密资产」三分类 | E1、E2 |
| C-04 | 3.1 自选 / 市场环境卡：风险偏好、趋势广度、波动状态 | `/watchlist` | 打开市场环境卡；检查风险偏好、趋势广度、波动状态、广度、共振、窗口和更新时间 | 三项状态都有真实值或明确“未生成”原因；广度和共振来自 `GET /api/market/breadth`；页面不在前端推算风险偏好、趋势广度和波动状态 | E1、E2 |

### 2.5 标的详情

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| D-01 | 3.1 详情 / 面包导航：自选 / 标的，下拉搜索并切换标的 | `/watchlist/<instId>` | 打开详情；点击面包导航；用下拉搜索另一个标的并切换；检查 URL 和周期 | 面包导航可回到自选；下拉能搜索并切换；切换后 URL 更新；切换标的保留当前周期，新标的该周期没有数据时显示「尚未同步」并触发对应周期同步，不回退到其他周期 | E1、E2 |
| D-02 | 3.1 详情 / 头部：名称、合约 ID、资产类别、最新价、涨跌；头部下方行情信息行显示标记价、指数价、数据时间、来源 | `/watchlist/<instId>` | 打开详情头部；切换现货和永续标的；与 `GET /api/instruments/<id>/analysis` 对比 | 名称、合约 ID、资产类别正确；头部右栏只显示最新价与涨跌幅；标记价、指数价、数据时间、来源在头部下方各显示一次；缺值写“尚未提供”，不填 0 | E1、E2 |
| D-03 | 3.1 详情 / K 线图：K 线卡内 1D / 4H / 1H 切换，MA20/MA60 叠加，缺口标注 | `/watchlist/<instId>` | 在「K 线与均线」卡片右上角依次切换 1D、4H、1H；检查 K 柱、MA20、MA60 和缺口；切换到一个尚未同步的周期 | 周期按钮只在 K 线卡内出现一次；三个周期始终可切换，切换即触发该周期按需同步；均线和缺口可见；缺数据时显示「尚未同步」或原因，不禁用周期；图表数据来自分析接口，不在前端合成 | E1、E2 |
| D-04 | 3.1 详情 / 指标卡：MA(20)、RSI(14)、MACD(12,26,9)、ATR(14) | `/watchlist/<instId>` | 打开指标卡；与 `GET /api/indicators` 或分析接口返回的指标对比 | 四个指标都有值和时间；数值与接口一致；缺样本时显示“样本不足”或空态，不编造 | E1、E2 |
| D-05 | 3.1 详情 / 趋势读数：Close、MA20、MA60、价格与均线距离、均线斜率 | `/watchlist/<instId>` | 打开趋势读数区；与 `GET /api/instruments/<id>/analysis` 的对应字段对比 | Close、MA20、MA60、价格与均线距离、5 根均线斜率都显示；数值与接口一致；没有足够 K 线时说明不足 | E1、E2 |
| D-06 | 3.1 详情 / 成交量读数：当前成交量、20 日均量、相对成交量 | `/watchlist/<instId>` | 打开成交量读数区；与接口返回的 `current`、`average20`、`relative` 对比 | 三项都显示；相对成交量与接口一致；没有 20 日均量时说明样本不足 | E1、E2 |
| D-07 | 3.1 详情 / 相对强弱：标的 N 日收益、基准 N 日收益、超额收益 | `/watchlist/<instId>` | 打开相对强弱区；检查标的收益、基准收益和超额收益；确认基准不是标的自身 | 三项都显示；基准标的明确；标的不会被选为自己的基准；样本不足时说明 | E1、E2 |
| D-08 | 3.1 详情 / 读数解释：按模板生成 2 到 3 句说明，不含买卖建议 | `/watchlist/<instId>` | 打开读数解释；逐句检查数值和措辞 | 2 到 3 句；每句含实际数值或明确条件；不出现“买入”“卖出”“建议加仓”等交易建议 | E1、E2 |
| D-09 | 3.1 详情 / 关键价位：近 20 日高点和低点、距现价百分比 | `/watchlist/<instId>` | 打开关键价位区；与接口的 high20、low20 和距离百分比对比 | 高点和低点都显示；距现价百分比符号正确；样本不足时说明 | E1、E2 |
| D-10 | 3.1 详情 / 相关性：60 日相关系数、有效样本数、计算窗口 | `/watchlist/<instId>` | 打开相关性区；检查系数、样本数、窗口；切换到样本不足的标的 | 三项都显示；样本不足时写“样本不足”；窗口与接口一致；不在前端重新计算 | E1、E2 |
| D-11 | 3.1 详情 / 关联策略：最近一个月回测收益、最大回撤、交易数、回测日期 | `/watchlist/<instId>` | 打开关联策略区；查看近 30 天回测；用同一策略版本、同一区间从详情页发起回测；再从策略页发起同一回测 | 显示收益、最大回撤、交易数、回测日期；两个入口的同一参数得到同一结果；没有关联策略时说明 | E1、E2、E3 |
| D-12 | 3.1 详情 / 提醒区：按标的过滤待处理提醒，支持确认与忽略 | `/watchlist/<instId>` | 打开提醒区；确认只显示当前标的；执行确认和忽略；刷新并检查活动 | 只显示当前标的待处理提醒；确认和忽略调用 `PATCH /api/alerts/<id>`；状态变化写入活动；重复处置有明确提示 | E1、E2、E3 |
| D-14 | 3.1 详情 / 数据覆盖：每个周期的起止时间、K 线数量、缺口数量、最后同步时间 | `/watchlist/<instId>` | 打开数据覆盖表；逐周期核对起止时间、数量、缺口数、最后同步时间 | 每个周期都有对应行；缺数据写“尚未同步”，不显示 0；最后同步时间来自数据库或接口，不由前端推算 | E1、E2、E3 |

### 2.6 持仓

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| E-01 | 3.1 持仓 / 持仓概览条：持仓市值、未实现盈亏、今日盈亏、OKX 同步状态 | `/positions` | 打开持仓页顶部概览条；与账户和持仓接口对比；刷新页面 | 显示持仓市值、未实现盈亏、今日盈亏和 OKX 同步状态；每项有来源或数据时间；没有汇总接口时明确显示“未提供”，不用前端临时求和冒充 | E1、E2 |
| E-02 | 3.1 持仓 / OKX 持仓只读区 | `/positions` | 打开 OKX 区；逐列核对标的、方向、数量、开仓均价、标记价、未实现盈亏、盈亏率、杠杆、保证金模式、强平价、保证金；检查页面没有下单入口 | 字段齐全并与 `/api/positions/exchange` 一致；没有下单、撤单、改单、平仓按钮；显示来源和截至时间；刷新后数据一致 | E1、E2、E3 |
| E-03 | 3.1 持仓 / 手动持仓：创建、买入、卖出、更正、清仓、操作流水 | `/positions` | 创建手动持仓；买入；卖出；更正；清仓；打开流水；刷新页面 | 每次操作写入不可覆盖的流水；数量和成本按流水重算；重复请求使用幂等键不重复入账；刷新后数量和成本一致；无行情时写“无行情源”，不用相似标的替代 | E1、E2、E3、E6 |
| E-04 | 3.1 持仓 / 敞口分布：多头名义价值、空头名义价值、单标的占比、行业敞口 | `/positions` | 打开敞口分布；与 `GET /api/risk/exposure` 对比；检查未分类行业 | 多头、空头名义价值、单标的占比、行业敞口都显示；计算口径与接口一致；未分类行业显示 `unclassified` 或“未分类”；没有持仓时显示空态 | E1、E2 |
| E-05 | 3.1 持仓 / 风险检查：临近止损、高杠杆、未设置止损、保证金使用率 | `/positions` | 打开风险检查；检查每条规则的规则 ID、值、阈值和级别；修改一条持仓的风险配置并刷新 | 每条风险能追溯到规则 ID、输入值、阈值和级别；保存后刷新仍生效；没有配置时显示“未设置”或明确空态 | E1、E2、E3、E6 |

### 2.7 策略与回测

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| F-01 | 3.1 策略与回测 / 策略列表：用户策略、当前版本、状态、标的数量、最近回测摘要 | `/strategies` | 打开策略页；检查列表每一列；点击进入策略详情 | 显示用户策略、当前版本、状态、标的数量和最近回测摘要；数值来自 `GET /api/strategies`；没有策略时显示空态 | E1、E2 |
| F-02 | 3.1 策略与回测 / 策略参数：周期、方向、规则 JSON、参数、仓位规则、版本 | `/strategies` | 打开策略详情；查看规则 JSON、参数、仓位规则和版本目录；切换旧版本 | 参数、规则 JSON、仓位规则和版本都可见；旧版本只读；数值和结构与接口一致 | E1、E2 |
| F-03 | 3.1 策略与回测 / 标的关联：策略版本的标的集合 | `/strategies` | 打开策略版本；查看标的集合；替换标的并保存；再打开旧版本 | 标的集合按版本保存；替换后当前版本更新，旧版本保持原集合；旧版本修改返回冲突或只读 | E1、E2、E3 |
| F-04 | 3.1 策略与回测 / 新建策略草稿 | `/strategies` | 点击新建；填写名称、规则和参数；保存；刷新 | 创建策略和第一个草稿版本；刷新后仍存在；规则非法时显示明确错误，不保存半成品 | E1、E2、E3 |
| F-05 | 3.1 策略与回测 / 回测发起：选择策略版本、标的、区间、成本、资金和数据源 | `/strategies` | 选择策略版本、标的、区间、成本、资金和数据源；发起回测；查看返回的运行 ID | 请求只使用 `strategy_version_id`；成功后写入策略与回测的关联；缺少数据或成本时阻止或明确降级；返回运行 ID | E1、E2、E3 |
| F-06 | 3.1 策略与回测 / 回测记录：运行列表、日期区间、参数、汇总指标和删除 | `/strategies` 或 `/backtests` | 打开回测记录；查看日期、参数、汇总指标；删除一条记录并确认 | 列表、日期区间、参数和汇总指标来自后端；删除后列表更新；删除失败有错误提示 | E1、E2、E3 |
| F-07 | 3.1 策略与回测 / 运行状态：信号扫描、行情订阅、自动执行、最近检查时间 | `/strategies` | 打开运行状态区；检查信号扫描、行情订阅、自动执行和最近检查时间 | 四项都有真实状态或明确“未实现”原因；行情订阅状态来自推送层；自动执行默认关闭；最近检查时间来自后端，不由前端推算 | E1、E2 |
| F-08 | 3.1 回测详情 / K 线买卖标记 | `/backtests?run=<run_id>` | 打开一条回测详情；检查 K 线上的买入和卖出标记；与交易明细对比 | 标记只来自 `backtest_trades`；每个标记的标的、方向、时间与交易明细一致；没有交易时不显示标记 | E1、E2 |
| F-09 | 3.1 回测详情 / 历史回放：播放、暂停、前后单步、速度选择、进度拖动 | `/backtests?run=<run_id>` | 打开回放；播放、暂停、前后单步、切换速度、拖动进度 | 回放只读已保存序列；播放、暂停、单步、速度和拖动都有效；不请求实时行情；结束时停在最后一条已保存数据 | E1、E2、E5 |
| F-10 | 3.1 回测详情 / 净值与回撤：策略净值、基准净值、回撤曲线 | `/backtests?run=<run_id>` | 打开净值和回撤区；检查策略净值、基准净值、回撤曲线 | 策略净值和回撤显示；基准没有保存时明确写“未保存”，不补假曲线；坐标轴和数据点可复核 | E1、E2 |
| F-11 | 3.1 回测详情 / 汇总指标：初始资金、最终资金、总收益、最大回撤、夏普、交易次数 | `/backtests?run=<run_id>` | 打开汇总指标；与 `GET /api/backtests/<id>` 对比 | 六项都显示；数值与接口一致；缺失时显示“未提供”或空态 | E1、E2 |
| F-12 | 3.1 回测详情 / 年化收益、胜率、盈亏比展示 | `/backtests?run=<run_id>` | 打开汇总卡；检查年化收益、胜率、盈亏比 | 三项都显示；胜率按后端比值换成百分数文案；数值与接口一致；不在前端重新计算 | E1、E2 |
| F-13 | 3.1 回测详情 / 交易明细：按盈利、亏损、方向和建仓日期筛选 | `/backtests?run=<run_id>` | 打开交易明细；按盈利、亏损、方向、建仓日期筛选；翻页 | 筛选结果与 `GET /api/backtests/<id>/trades` 一致；分页正确；没有匹配时显示空态 | E1、E2 |
| F-14 | 3.1 回测详情 / 交易明细 CSV 导出 | `/backtests?run=<run_id>` | 设置筛选条件；导出 CSV；用文本编辑器打开 | CSV 为 UTF-8 带 BOM；列顺序为标的、方向、开仓时间、开仓价、平仓时间、平仓价、数量、手续费、资金费、滑点、净盈亏、退出原因；内容与当前筛选一致 | E1、E2 |
| F-15 | 3.1 回测详情 / 写复盘：创建关联 `backtest_id` 的研究记录 | `/backtests?run=<run_id>` | 点击“写复盘”；检查跳转和预填；保存；回到记录页查看 | 跳转到 `/journal?new=1&type=review&backtest=<id>`；记录页预填复盘类型和回测关联；保存后记录关联到该回测 | E1、E2、E3 |

### 2.8 记录

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| G-01 | 3.1 记录 / 记录页骨架和入口 | `/journal` | 从主导航进入记录页并刷新 | 页面能打开，标题正确，列出记录区；不出现 404 或空白页 | E1 |
| G-02 | 3.1 记录 / 研究记录：创建、编辑、删除、按类型筛选、按时间排序 | `/journal` | 创建一条记录；编辑标题和内容；按类型筛选；切换时间排序；删除 | 创建、编辑、删除都调用真实接口；筛选和排序结果正确；删除需要确认；刷新后状态一致 | E1、E2、E3、E6 |
| G-03 | 3.1 记录 / 记录关联：标的、策略、回测和标签 | `/journal` | 创建或编辑记录；关联标的、策略、回测和标签；点击关联对象；删除被关联对象后重新打开 | 关联对象可保存和跳转；引用不存在时接口返回 404；被引用对象删除后引用置空；标签正确显示 | E1、E2、E3 |
| G-04 | 3.1 记录 / 活动时间线：按事件类型与北京时间日期筛选、分页读取 | `/journal` | 打开活动时间线；按事件类型和北京时间日期筛选；翻页 | 筛选和分页结果来自 `GET /api/activity`；时间按北京时间显示；没有匹配时显示空态 | E1、E2 |

### 2.9 设置

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| H-01 | 3.1 设置 / 行情与推送：连接状态、订阅标的、最后同步、失败次数 | `/settings` | 打开设置页；确认没有 Provider 输入框；查看订阅标的、最后同步、失败次数；逐项编辑订阅标的并保存 | 页面没有 Provider 输入框；`GET /api/settings` 的 `data_sources` 不含 `provider`；订阅标的可以逐项输入和删除；保存后刷新仍保留；最后同步和失败次数来自同步任务表，不由前端推算 | E1、E2、E3 |
| H-02 | 3.1 设置 / 显示偏好：涨跌配色、默认周期、价格精度、首页布局 | `/settings` | 修改涨跌配色、默认周期、价格精度、首页布局；保存；刷新 | 修改后立即生效；刷新后仍保留；非法值被拒绝并提示；不影响其他设置分组 | E1、E2、E3 |
| H-03 | 3.1 设置 / 风险默认值：默认杠杆、单笔风险预算、预警阈值、止损规则 | `/settings` | 修改四项风险默认值；保存；刷新；再改回原值 | 四项保存成功；刷新后保留；与执行风控限额分开；非法值被拒绝 | E1、E2、E3 |
| H-04 | 3.1 设置 / 交易连接和密钥状态：API Key 只写不读、Secret 和 Passphrase 不回显 | `/settings` | 打开连接与密钥区；检查页面和 `GET /api/settings` 的 `secrets`；在 DevTools 查看响应 | 页面不显示 API Key 明文；`GET /api/settings` 只返回 `okx_api_key_masked`、`okx_configured`、`okx_permission`；Secret 和 Passphrase 不出现在响应或页面；不提交真实 Key | E1、E2 |
| H-05 | 3.1 设置 / 系统健康：数据库、OKX REST、OKX WebSocket、任务队列、K 线覆盖 | `/settings` | 打开系统健康；逐项检查五项状态、最后成功时间、错误和详情；与 `GET /api/system/health` 对比 | 五项独立检查，单项异常不影响其他项；每项有 `status`、`last_success_at`、`error`、`detail`；`components` 不含 `external_provider`；异常项排在前面；缺失最后成功时间写“暂无成功记录”；不把陈旧数据报告为 `ok` | E1、E2 |
| H-06 | 3.1 设置 / 通知：浏览器通知通道开关与权限状态 | `/settings` | 打开设置页的通知卡；查看浏览器权限文案；点击「开启浏览器通知」；关闭「浏览器通知通道」并保存；刷新页面后再打开；重新开启通道并保存 | 权限状态按三种情况显示：已允许、已被浏览器拒绝、尚未授权，浏览器不支持系统通知时写「不支持」；「开启浏览器通知」在已允许时禁用并显示「已允许」，未授权时点击后由浏览器询问，被拒绝时提示到浏览器站点设置里手动改回允许；关闭通道后服务端不再广播告警，页面也不弹通知，`GET /api/settings` 的 `notifications.channels` 为空数组；重新开启并保存后恢复弹窗，`GET` 与页面开关一致；页面明说通知只在页面打开时有效 | E1、E2、E3 |

### 2.10 数据推送

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| I-01 | 3.2 推送 / WebSocket `/api/stream` 及九类事件 | 自选、详情、持仓、首页 | 打开浏览器 DevTools 的 WebSocket 帧；连接 `/api/stream`；观察 `market.quote.updated`；执行一次账户同步、提醒处置、活动写入和回测；断网后恢复 | 浏览器不直接连接 OKX，只连接服务端 `/api/stream`；价格、账户、持仓、提醒、活动、回测状态事件带来源和时间；断线后能重连并补齐快照；无法触发的事件类型逐项记 `BLOCKED` 并写原因 | E5、E2 |

推送九类事件分别为：`market.quote.updated`、`account.snapshot.updated`、`position.updated`、`alert.created`、`alert.updated`、`activity.created`、`strategy.signal.created`、`backtest.status.updated`、`data_source.status.updated`。不得用脚本伪造帧、MSW 或假 WebSocket 作为通过证据。

### 2.11 接口功能点

接口功能点用于直接验证 3.2 的 29 行。`API` 默认是 `http://127.0.0.1:8000/api`；执行前导出：

```bash
export API="http://127.0.0.1:8000/api"
```

| 编号 | 覆盖 PRD 行 | 接口 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| P-01 | 3.2 首页 / `GET /api/dashboard/summary` | `GET /api/dashboard/summary` | `curl -sS -w '\n%{http_code}\n' "$API/dashboard/summary"` | 200；包含 `market`、`account`、`risk`、`positions`、`watchlist`、`alerts`、`strategies`、`activity` 八个模块；每个模块有 `status`、`as_of`、`error`、`data`；不可用模块有原因，不返回其他模块数据冒充 | E2 |
| P-02 | 3.2 市场 / `GET /api/market/overview` | `GET /api/market/overview` | `curl -sS -w '\n%{http_code}\n' "$API/market/overview"` | 200；`items` 只有 `symbol=BTC` 一项（行情取 `instId=BTC-USDT`）；`source=okx_spot`、`value` 非空；每项有 `as_of`、`is_delayed`、`quality_status`；顶层有 `stale`、`stale_reason`，不含 `provider` 与 `last_success_at`；失败项 `value=null`、`quality_status=missing` | E2 |
| P-02a | 3.4 已删除 / `GET /api/market/events`、`GET /api/news` | 两个已删除接口 | `curl -s -o /dev/null -w '%{http_code}\n' "$API/market/events"`；对 `"$API/news"` 重复一次 | 两个请求都返回 404；路由不存在；`market_events`、`news_items` 两张表不存在 | E2、E3 |
| P-03 | 3.2 标的 / `GET /api/instruments?query=` | 实际路径 `GET /api/instruments/search?q=` | `curl -sS -w '\n%{http_code}\n' "$API/instruments/search?q=AAPL"` | 200；能按关键字返回真实标的；不存在的关键字返回空结果而不是错误标的；PRD 行写的 `query` 与证据列的实际路径差异在报告中记录 | E2 |
| P-04 | 3.2 自选 / `GET /api/watchlist`、`POST /api/watchlist/items` 等效接口、`DELETE /api/watchlist/items/{id}` 等效接口 | `GET /api/watchlist`、`POST /api/watchlist`、`DELETE /api/watchlist/{inst_id}` | 读取列表；加入一个可交易标的；重复加入；删除；再读取 | GET 200；POST 201 或对应成功码；重复加入不产生重复行；DELETE 成功；删除后列表不再包含；错误标的返回明确错误 | E2、E3 |
| P-05 | 3.2 标的 / `GET /api/instruments/{id}/analysis?bar=1d、4h、1h` | `GET /api/instruments/{id}/analysis` | 对同一标的依次请求 `bar=1d`、`bar=4h`、`bar=1h` | 200；返回对应周期 K 线、MA20/MA60、指标、趋势、成交量、相对强弱、关键价位、相关性、覆盖；数据不足时字段为空并给原因，不返回假数据 | E2 |
| P-06 | 3.2 持仓 / `GET /api/positions` 合并视图 | `GET /api/positions` | `curl -sS -w '\n%{http_code}\n' "$API/positions"` | 200；返回合并视图；每项有来源字段，能区分 `exchange` 与 `manual`；没有来源字段或返回 404/405 记 `FAIL` | E2 |
| P-07 | 3.2 持仓 / `POST /api/manual-positions`、`POST /api/manual-positions/{id}/trades`、`GET /api/manual-positions/{id}/trades` | 三个手动持仓接口 | 创建一个手动持仓；用同一幂等键重复创建；写入一笔流水；读取流水；再写入一笔更正或清仓流水 | 创建 201；重复幂等键返回同一持仓；流水 201；读取流水按时间倒序并带操作后数量与成本；重复流水幂等键不重复入账 | E2、E3、E6 |
| P-08 | 3.2 提醒 / `GET /api/alerts`、`PATCH /api/alerts/{id}` | 两个提醒接口 | `GET /api/alerts?status=pending`；对一条待处理提醒 `PATCH` 为 `acknowledged`；再次 `PATCH` 同一提醒 | GET 200 并支持筛选与分页；PATCH 成功并写活动；重复处置返回 409 或明确冲突；没有待处理提醒时记 `BLOCKED`，不伪造提醒 | E2、E3 |
| P-09 | 3.2 活动 / `GET /api/activity` | `GET /api/activity` | `curl -sS -w '\n%{http_code}\n' "$API/activity"`；带 `event_type`、时间范围与分页参数各请求一次 | 200；按时间倒序；筛选和游标分页有效；每条有事件类型、对象和时间 | E2 |
| P-10 | 3.2 策略 / `GET`、`POST /api/strategies`；`GET`、`PUT /api/strategies/{id}` | 策略接口 | 创建草稿策略；读取列表和详情；修改元数据；提交版本字段创建下一版；读取版本目录 | 创建返回策略与草稿版本；列表和详情字段与页面一致；只改元数据不建版本；提交版本字段建下一版；非法规则返回明确错误 | E2、E3 |
| P-11 | 3.2 回测 / `POST /api/backtests`、`GET /api/backtests/{id}` | 回测发起与详情 | 用页面发出的真实请求体重放 `POST /api/backtests`；读取返回的运行；再请求 `GET /api/backtests/{id}` | 只接受 `strategy_version_id`；返回 `run_ids`、`combination`、`group_equity`；写入策略与回测关联；详情与列表一致；缺少数据时明确阻止或降级 | E2、E3 |
| P-12 | 3.2 回测 / `GET /api/backtests/{id}/chart`、`/equity`、`/trades`、`/trades.csv`、`/replay` | 五个回测详情接口 | 对同一条回测依次请求五个接口； CSV 用 `curl -o` 保存后检查 BOM 和列顺序；回放检查只读已保存序列 | 五个接口都 200；图表标记来自 `backtest_trades`；净值基准缺失时为 `null`；交易筛选与分页正确；CSV 编码和列顺序正确；回放不访问实时行情 | E2、E3 |
| P-13 | 3.2 记录 / `GET`、`POST /api/research-notes`；`PUT`、`DELETE /api/research-notes/{id}` | 研究记录接口 | 创建记录；列表按类型和关联对象筛选；更新；删除；再读取 | 创建 201；列表支持筛选、排序和游标；更新成功；删除 204；不存在返回 404；关联对象不存在返回 404 | E2、E3 |
| P-14 | 3.2 设置 / `GET`、`PATCH /api/settings` 的 v6 分组 | 设置接口 | `GET /api/settings`；`PATCH` 修改 `display`、`risk_defaults` 或 `notifications.channels`；再 `GET`；恢复原值 | 只返回 `display`、`risk_defaults`、`execution.auto_trading_enabled`、`data_sources`、`notifications` 与只读 `secrets`；不返回成本、回测默认值和执行风控限额；`GET` 返回 `notifications.channels`，`PATCH` 改 `channels` 后 `GET` 一致；PATCH 后 GET 一致；响应不含 API Key 明文 | E2、E3 |
| P-15 | 3.2 健康 / `GET /api/system/health` | 健康接口 | `curl -sS -w '\n%{http_code}\n' "$API/system/health"` | 200；五项组件各自有 `status`、`last_success_at`、`error`、`detail`；`components` 不含 `external_provider`；单项异常不影响其他项；不把陈旧数据报告为 `ok` | E2 |
| P-15a | 3.4 已删除 / 外部 Provider 与代理行情 | 健康与回测接口 | `GET /api/system/health` 检查组件名；`GET /api/backtests?data_source=us_equity_proxy` 与不合法 `data_source` 各请求一次 | `components` 不含 `external_provider`；`GET /api/settings` 的 `data_sources` 不含 `provider`；回测接口拒绝 `us_equity_proxy`；数据库没有该来源的 K 线 | E2、E3 |
| P-16 | 3.2 同步 / `POST /api/system/sync` | 手动同步接口 | 用 `dataset=instruments` 请求同步；再请求未知数据集与仍在运行的数据集 | 合法请求成功并写 `data_sync_jobs`；未知数据集或参数不合法返回 400；同一数据集仍在运行返回 409；响应包含本次结果；请求不再接受 `provider` | E2、E3 |
| P-17 | 3.2 推送 / WebSocket `/api/stream` 及九类事件 | WebSocket `/api/stream` | 用 `websocat` 或浏览器连接；触发价格、账户、持仓、提醒、活动和回测事件；记录每类事件的帧 | 连接成功；事件帧有类型、数据和 `as_of`；九类事件要么观察到真实帧，要么逐项记 `BLOCKED` 并写原因；不得用假帧 | E5 |

### 2.12 后端保留能力

3.3 的五项能力不通过 v6 页面暴露，只做回归验证，不计入页面功能是否正确，但必须确认接口没有被错误暴露、原测试仍通过。

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| R-01 | 3.3 执行 / 执行引擎：订单状态机、模拟成交、对账、重启恢复 | 无页面；`backend/app/execution/` | 运行 `cd backend && ../.venv/bin/python -m pytest tests/execution -q`；检查没有 v6 页面入口 | 测试通过；页面没有真实下单入口；执行能力保留给后续阶段 | E4、E1 |
| R-02 | 3.3 风控 / 风控规则、分级处置、风险事件读取 | 无页面；`backend/app/risk/` | 运行 `cd backend && ../.venv/bin/python -m pytest tests/risk -q`；检查页面只读风险结果 | 测试通过；页面不提供风控编辑入口；风险结果来自后端 | E4、E1 |
| R-03 | 3.3 审批 / 策略审批状态机 | 无页面；`backend/app/strategy/approval.py` | 运行 `cd backend && ../.venv/bin/python -m pytest tests/api/test_approval.py -q` | 测试通过；v6 策略页不提供审批入口 | E4、E1 |
| R-04 | 3.3 组合 / 组合虚拟持仓、资金分配、敞口和调整申请 | 无页面；`backend/app/portfolio/` | 运行 `cd backend && ../.venv/bin/python -m pytest tests/portfolio -q` | 测试通过；v6 不提供组合页面 | E4、E1 |
| R-05 | 3.3 流水 / 交易流水聚合 | 无页面；`backend/app/journal/` | 运行 `cd backend && ../.venv/bin/python -m pytest tests/journal -q`；请求 `GET /api/journal` | 测试通过；旧 HTTP 路由 `GET /api/journal` 返回 404 | E4、E2 |

### 2.13 按需同步

按需同步是 MKACG-855 的交付内容，覆盖 3.1 自选与详情两行、3.2 的 `POST /api/instruments/{id}/sync`。它和上面 83 个功能点分开编号，但计入功能点总数。

| 编号 | 覆盖 PRD 行 | 页面路径 | 操作步骤 | 预期结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| S-01 | 3.1 自选 / 搜索；3.2 标的 / `GET /api/instruments?query=` | `/watchlist` | 记录 `data_sync_jobs` 行数；在自选页搜索一个尚未加入自选的标的；再次查询 `data_sync_jobs` 行数 | 搜索返回 200 和结果；`data_sync_jobs` 行数不变，没有新增任何标的或 K 线任务；后端日志没有 OKX 行情请求 | E1、E2、E3、E4 |
| S-02 | 3.1 自选 / 加入自选 | `/watchlist` | 记录 `data_sync_jobs` 行数；加入一个尚未同步日线的标的；等待后台任务；查询该标的的日线覆盖与最新行情 | 加入返回 201，条目立即出现；新增 1 条 `dataset=candles` 的任务记录；同步完成后自选列表出现价格、涨跌幅和指标；上游失败时仍返回 201，任务记为失败并保留原因，页面显示「尚未同步」而不是错误弹窗 | E1、E2、E3、E6 |
| S-03 | 3.2 标的 / 按需同步；3.1 详情 / K 线图与数据覆盖 | `/watchlist/<instId>` | 清空该标的 `1d` 数据；打开详情；观察网络请求与 `data_sync_jobs`；等待数据出现 | 页面先显示已有数据或「尚未同步」；随后请求 `POST /api/instruments/{id}/sync`，返回 202 且 `status=started`；不等待同步完成；同步完成后指标与 K 线在有限次重读内更新，最多 3 次（2 秒、6 秒、12 秒） | E1、E2、E3、E5 |
| S-04 | 3.2 标的 / 按需同步 | 接口 | 对同一标的同一周期在同步进行中再次请求；成功后 60 秒内再次请求；切换到 `4h` 再请求 | 进行中返回 `already_running`，不新增任务；60 秒内返回 `fresh`，不新增任务；`4h` 返回 `started`，只新增 1 条 `bar=4h` 任务，`1d` 任务数不变；同时发起 10 个相同请求只产生 1 个后台任务 | E2、E3 |
| S-05 | 3.2 标的 / 按需同步；3.1 详情 / 数据覆盖 | 接口与 `/watchlist/<instId>` | 让上游返回 429 或超时；请求同步；打开详情；查询 `data_sync_jobs` | `POST /sync` 仍返回 202，不是 500；`data_sync_jobs` 记录该次失败与原因，状态为 `failed`；详情页可打开并显示「尚未同步」「数据不足」或「同步失败，可稍后重试」；已有数据不被清空，也不补造 K 线 | E1、E2、E3 |

| 字段 | 说明 |
| --- | --- |
| 请求 | `bar` 可选，取 `1d`、`4h`、`1h`，默认 `1d`；`days` 可选，`1..3650`，缺省按周期取 `1d=400`、`4h=90`、`1h=30` |
| 响应 | 202：`inst_id`、`bar`、`days`、`status`（`started`、`already_running`、`fresh`、`backoff`）、`requested_at` |
| 错误 | 标的未登记 404；周期或天数非法 422；调度器未启动 503；参数错误不启动任务 |
| 去重与冷却 | 键为 `(inst_id, bar)`；运行中 `already_running`；成功 60 秒内 `fresh`；失败 30 秒内 `backoff`；并发上限默认 2，由 `ON_DEMAND_SYNC_MAX_CONCURRENCY` 配置 |

复现命令：

```bash
export API="http://127.0.0.1:8000/api"
export INST="XAAPL-USDT"

# 搜索：不产生同步任务
BEFORE=$(podman exec trading-db psql -U trading -d trading -Atc \
  "select count(*) from v6_accept.data_sync_jobs")
curl -sS -w '\n%{http_code}\n' "$API/instruments/search?q=SPCX"
AFTER=$(podman exec trading-db psql -U trading -d trading -Atc \
  "select count(*) from v6_accept.data_sync_jobs")
echo "before=$BEFORE after=$AFTER"

# 详情：首次 started，进行中 already_running，成功后 fresh
curl -sS -X POST -H 'content-type: application/json' -d '{"bar":"1d"}' \
  -w '\n%{http_code}\n' "$API/instruments/$INST/sync"
curl -sS -X POST -H 'content-type: application/json' -d '{"bar":"1d"}' \
  -w '\n%{http_code}\n' "$API/instruments/$INST/sync"

# 参数错误不建任务
curl -sS -X POST -H 'content-type: application/json' -d '{"bar":"5m"}' \
  -w '\n%{http_code}\n' "$API/instruments/$INST/sync"
curl -sS -X POST -H 'content-type: application/json' -d '{"bar":"1d","days":0}' \
  -w '\n%{http_code}\n' "$API/instruments/$INST/sync"

# 任务流水
podman exec trading-db psql -U trading -d trading -P pager=off -c \
  "select provider, dataset, status, params, started_at, finished_at
     from v6_accept.data_sync_jobs order by started_at desc limit 5"
```

## 3. 判定规则

### 3.1 PASS

一个功能点同时满足以下条件才记为 `PASS`：

- 在真实页面、真实接口或真实数据库上观察到预期结果，操作步骤可重复。
- 证据包含 URL、命令、HTTP 状态码、关键响应字段或数据库查询结果；只凭“看起来正常”不算通过。
- 数据带来源和时间；行情、账户、持仓、提醒、活动、回测数据能追溯到真实来源。
- 页面没有演示数据、fixture、硬编码业务数值或前端伪造的派生值。
- 没有把旧值、延迟值、模拟值或回测值显示成当前实时值。
- 写入类操作刷新后仍然一致，重复请求不会重复入账。

一个功能点包含多个子项时，所有子项都通过才记 `PASS`。只通过一部分记 `FAIL`，并在失败清单里写出未通过的子项。

### 3.2 FAIL

出现下列任一情况记 `FAIL`：

- 预期功能缺失、字段缺失、数值错误、状态错误或操作无效。
- 页面显示假数据、演示数据、fixture、硬编码数值，或前端自行计算本应由后端返回的派生值。
- 同一数据在页面、接口和数据库之间不一致，且不是明确标注的延迟或快照差异。
- 写入后刷新丢失、重复入账、幂等键失效，或操作没有留下流水和活动记录。
- 接口返回 404、405、500，或返回结构与 PRD 不一致。
- 真实数据源不可用，但页面没有显示不可用或陈旧状态，而是继续显示旧值或假值。

`FAIL` 必须能复现。报告中的失败清单要写清功能点编号、复现步骤、期望结果、实际结果、证据和受影响的功能点。

### 3.3 BLOCKED

下列情况记 `BLOCKED`，不得记 `PASS`：

- OKX 模拟盘凭据缺失、网络不可达或 OKX 公共行情不可用，导致必须由真实数据证明的子项无法执行。
- 数据库、迁移、前端构建或后端进程无法启动。
- 需要一个当前无法触发的业务条件，例如没有待处理提醒、没有可用的策略版本或没有已保存的回测结果，且不能通过正常业务操作产生。
- 页面正确显示“不可用”“陈旧”或“暂无数据”，但功能点要求验证真实数据本身。

`BLOCKED` 必须写出阻塞原因、已经确认的事实、重试条件和责任人。页面降级行为可以作为单独的 `PASS` 子项记录，但不能抵消 `BLOCKED`。数据源恢复后必须重跑该功能点。

### 3.4 不作为通过证据

以下内容不能作为 `PASS` 证据：

- MSW、演示后端、`frontend/src/mocks/` 的 fixture、手工插入的数据库假数据。
- 假 WebSocket 帧、脚本伪造的事件、截图中的静态占位数字。
- 只阅读代码、只运行单元测试、只看类型检查结果。
- 与验收提交不一致的旧截图、旧接口响应或旧数据库结果。
- 未标明来源、时间、接口或数据库查询的“口头确认”。

### 3.5 总体结论

- 全部 88 个功能点 `PASS`：结论为“通过”。
- 存在任一 `FAIL`：结论为“不通过”，进入第 4 节的失败处理。
- 没有 `FAIL` 但存在 `BLOCKED`：结论为“有阻塞”，不得宣布 v6 验收通过；列出重试条件和责任人。
- 存在未覆盖的 PRD 行（覆盖率低于 `95/95`）：结论为“不通过”，先补清单或补验收。

## 4. 失败处理

### 4.1 创建修复 issue

每个 `FAIL` 创建一个修复 issue。多个 `FAIL` 如果确认是同一根因，可以合并为一个修复 issue，但描述里必须列出全部相关功能点编号。修复 issue 放在 trading 项目，parent 为 MKACG-807，指派赛博刘刘马（`92160cee-3863-48b9-a2db-88c250f00f65`）。

在 Multica 运行环境中，把下面的 `multica` 换成 `"$MULTICA_CLI_PATH"`。描述文件写在工作目录内，不使用 `/tmp` 或共享路径。

```bash
multica issue create \
  --project 834448e2-d47d-4bd9-95d4-e66f4aa946c6 \
  --parent 01a1d436-ebe4-73b2-a44b-0243572117a5 \
  --assignee-id 92160cee-3863-48b9-a2db-88c250f00f65 \
  --priority high \
  --title "[验收失败] <功能点编号> <一句话描述>" \
  --description-file ./acceptance-failure-<功能点编号>.md
```

修复 issue 描述必须包含：

- 功能点编号和对应的 `docs/prd/v6.md` 行。
- 验收提交、环境与数据时间。
- 复现步骤，按顺序写清点击、输入、接口请求或数据库查询。
- 期望结果和实际结果，分别列出。
- 证据：接口响应、数据库查询结果、截图说明或推送帧；不要只写“页面不对”。
- 受影响的功能点和其他可能受影响的页面。
- 验收项编号（例如 `B-04`）和原始验收报告链接或评论 ID。

### 4.2 修复和复验

- 修复由赛博刘刘马在对应 issue 内完成，验收人员不直接改代码。
- 修复 issue 全部关闭后，先重跑对应的 `FAIL` 项，再重跑与其共享代码或数据的 `PASS` 项。
- 修复提交改变验收对象时，原 `PASS` 证据不再适用于新提交；受影响的 `PASS` 项必须重跑。
- 复验仍失败时，在原修复 issue 内补充新证据，不新建重复 issue。
- 复验通过后，更新验收报告中的失败清单、修复 issue 和结论；只有全部 `FAIL` 关闭且复验通过，才能把总体结论改为“通过”。

### 4.3 BLOCKED 的处理

- `BLOCKED` 不创建修复 issue，只记录阻塞原因、重试条件和责任人。
- 环境或数据源恢复后，重跑对应功能点，并把结果写回原报告。
- 如果阻塞持续存在，必须在报告中明确写出对 v6 验收结论的影响，不得用“暂时跳过”代替。

## 5. 报告格式

验收报告使用 Markdown，发布在 issue 评论中。报告必须包含以下部分：

```markdown
## v6 真实验收报告

- 验收时间：
- 验收人：
- 验收对象：<master 提交或 PR head>
- 环境：podman 数据库、schema `v6_accept`、后端 `0.0.0.0:8000`、前端预览端口
- 凭据来源：环境变量 / `~/.okx/config.toml` 的 `[profiles.okx-demo]`
- OKX 模式：模拟盘只读，`OKX_DEMO=1`
- 数据时间：<各数据源的 as_of 或 captured_at>

### 汇总

| 项目 | 数值 |
| --- | ---: |
| 功能点总数 | 88 |
| PASS |  |
| FAIL |  |
| BLOCKED |  |
| PRD 行覆盖率 | /95 |

### 失败清单

| 功能点 | 期望 | 实际 | 证据 | 修复 issue |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

### 阻塞清单

| 功能点 | 阻塞原因 | 已确认事实 | 重试条件 | 责任人 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

### 环境与数据源

- 后端健康检查：
- 前端构建：
- 数据库 schema 与迁移版本：
- 数据时间与陈旧状态：

### 结论

<通过 / 不通过 / 有阻塞>：<一句话依据>
```

如果某个功能点的证据较多，可以在报告末尾增加“证据索引”，按功能点编号列出 `E1` 至 `E6` 的具体内容。报告不得只写汇总数字而不写失败和阻塞明细。

## 6. 边界

- 不执行真实下单、撤单、改单、平仓、资金划转和提现。
- OKX 只使用模拟盘只读接口，不切换到实盘，不修改账户设置。
- 不修改业务代码、配置、迁移、测试或 PR；发现问题只创建修复 issue。
- 不手工插入 fixture、演示数据、假 K 线或假账户快照。
- 不把 mock、MSW、演示后端、假 WebSocket 或静态占位数值当作通过证据。
- 不打印、复制或提交 API Key、Secret 和 Passphrase。
- 不删除 `public` schema、数据库容器或容器数据卷；只清理 `v6_accept`。
- 不把公开行情、模拟盘数据或回测数据描述成实盘数据。
- 不因为页面“看起来正常”就跳过接口和数据库核对。
- 验收不通过时，不在报告中写“基本通过”或“除少数问题外通过”。

## 7. 与交付计划的关系

`docs/prd/v6-delivery.md` 的阶段 7 包含两个节点：

- **S7-1 全站验收**：清理演示数据和环境标签，端到端走查全部页面，执行旧代码残留检查，核对 `docs/prd/v6.md` 的每行状态与代码一致。
- **S7-2 真实功能验收清单与执行规则**：编写本文，定义验收环境、功能点清单、判定规则、失败处理、报告格式和边界。

两个节点的关系：

1. S7-1 与 S7-2 可以并行；S7-1 负责让代码和文档处于可验收状态，S7-2 负责定义验收清单和规则。
2. 验收唤醒只在 S7-1 与 S7-2 都合并后创建，由总控 issue 放置；唤醒对象是 Mika，执行对象是合并后的 `master` 提交或任务指定的 PR head。
3. S7-2 本身不启动应用、不执行验收、不创建修复 issue。验收执行发生在唤醒之后，按本文第 1 节到第 6 节进行。
4. 验收报告中的每个 `FAIL` 都要创建修复 issue，修复完成后复验；全部 `FAIL` 关闭并通过复验后，阶段 7 才能关闭。
5. 如果 S7-1 的清理或 PRD 核对改变了验收对象，S7-2 的验证必须在新提交上重跑，旧报告不再作为最终结论。
