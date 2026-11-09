#!/usr/bin/env bash
# 1.0 一键全链路验收脚本（MKACG-703 / S12-01）。
#
# 目标链：基础设施 → 行情同步/回补 → 相关性 → 全市场扫描 → 策略生成与审批 →
#         历史回测 → 风控限额 → paper 执行 → MCP 查询 → 收尾断言。
#
# 约束（见 docs/architecture/contract 与 docs/mcp.md）：
#   * 只通过 HTTP 调用 API，不 import 后端模块、不直连业务表；
#     `docker compose` 只用于三件事：步骤 0 读容器健康与 alembic 版本，
#     以及步骤 7 之后不做任何数据清理。
#   * 所有异步任务都以轮询 `GET /ops/job-runs/{id}` 等待终态，不用固定 sleep。
#   * 每一步独立可复跑：请求参数由数据推导且在同一天内确定，
#     因此重复执行时服务端按 job_key / strategy_key / run_key / client_order_id
#     命中幂等分支，不新增业务行。
#   * 真实交易全程关闭：脚本不调用任何真实下单接口，收尾断言 mode=real 订单为 0。
#
# 退出码：0 = 全部步骤通过；非 0 = 某一步失败（标准错误会打印失败步骤名与步骤号）。
#
# 产物：默认写 $HOME/.cache/s12/full-smoke-artifacts.json，不弄脏工作区；
# 需要刷新仓库内的 docs/reports/full-smoke-artifacts.json 时显式指定：
#   ARTIFACT=docs/reports/full-smoke-artifacts.json bash scripts/e2e/full_smoke.sh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"

API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE=${API_BASE:-$API_ROOT/api/v1}
MCP_ROOT=${MCP_ROOT:-$API_ROOT/mcp}

# 回补窗口：同一个 UTC 日期内取值恒定，保证重复执行命中同一 job_key。
E2E_START=${E2E_START:-2025-06-01T00:00:00Z}
E2E_END=${E2E_END:-$(date -u -d '+1 day' +%Y-%m-%dT00:00:00Z)}

POLL_TIMEOUT=${POLL_TIMEOUT:-600}
POLL_INTERVAL=${POLL_INTERVAL:-2}

TARGET_SYMBOL=${TARGET_SYMBOL:-GOOGL}
TARGET_EXCHANGE=${TARGET_EXCHANGE:-XNAS}
RELATION_WINDOW=${RELATION_WINDOW:-60}
RS_LOOKBACK=${RS_LOOKBACK:-60}
BACKTEST_DAYS=${BACKTEST_DAYS:-120}

STRATEGY_NAME=${STRATEGY_NAME:-"s12 full smoke strategy"}
STRATEGY_MARKER=${STRATEGY_MARKER:-s12-full-smoke}
MCP_CLIENT_NAME=${MCP_CLIENT_NAME:-s12-full-smoke-read}
ORDER_CLIENT_ID=${ORDER_CLIENT_ID:-s12-full-smoke-entry-1}
EVALUATION_KEY=${EVALUATION_KEY:-"${STRATEGY_MARKER}-$(date -u +%Y-%m-%d)"}
ORDER_QUANTITY=${ORDER_QUANTITY:-1}

ARTIFACT=${ARTIFACT:-$HOME/.cache/s12/full-smoke-artifacts.json}

mkdir -p "$HOME/.cache"
WORK_DIR=$(mktemp -d "$HOME/.cache/full-smoke.XXXXXX")
trap 'rm -rf -- "$WORK_DIR"' EXIT

CURRENT_STEP=""
STEP_NAME=""
STEP_T0=0
HTTP_STATUS=""
HTTP_BODY=""
MCP_TOKEN=""
declare -a SUMMARY_ROWS=()
declare -a ARTIFACT_ENTRIES=()

# ---------------------------------------------------------------- 基础设施

fail() {
  printf '\n[FAIL] 步骤 %s（%s）：%s\n' "${CURRENT_STEP:-?}" "${STEP_NAME:-?}" "$*" >&2
  exit 1
}

step_begin() {
  CURRENT_STEP=$1
  STEP_NAME=$2
  STEP_T0=$(date +%s%3N)
  printf '\n=== 步骤 %s：%s\n' "$CURRENT_STEP" "$STEP_NAME"
}

step_end() {
  local http=$1 note=$2
  local ms=$(( $(date +%s%3N) - STEP_T0 ))
  printf '  ✓ HTTP %s，耗时 %sms，%s\n' "$http" "$ms" "$note"
  SUMMARY_ROWS+=("$CURRENT_STEP|$STEP_NAME|$http|$ms|$note")
}

# http METHOD PATH [JSON_BODY]
# 结果写入 HTTP_STATUS / HTTP_BODY。
http() {
  local method=$1 path=$2 data=${3-} out
  if [[ -n $data ]]; then
    out=$(curl -sS -X "$method" "$API_BASE$path" \
      -H 'Content-Type: application/json' -d "$data" -w $'\n%{http_code}') \
      || fail "请求失败：$method $API_BASE$path"
  else
    out=$(curl -sS -X "$method" "$API_BASE$path" -w $'\n%{http_code}') \
      || fail "请求失败：$method $API_BASE$path"
  fi
  HTTP_STATUS=${out##*$'\n'}
  HTTP_BODY=${out%$'\n'*}
  return 0
}

expect_status() {
  local expected=$1
  [[ $HTTP_STATUS == "$expected" ]] || fail "期望 HTTP $expected，实际 $HTTP_STATUS；响应：$HTTP_BODY"
}

# mcp_call TOKEN JSON_BODY：POST /mcp，结果写入 HTTP_STATUS / HTTP_BODY。
mcp_call() {
  local token=$1 data=$2 out
  out=$(curl -sS -X POST "$MCP_ROOT" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' -d "$data" -w $'\n%{http_code}') \
    || fail "请求失败：POST $MCP_ROOT"
  HTTP_STATUS=${out##*$'\n'}
  HTTP_BODY=${out%$'\n'*}
  return 0
}

poll_job() {
  local run_id=$1 deadline status
  deadline=$(( SECONDS + POLL_TIMEOUT ))
  while true; do
    http GET "/ops/job-runs/$run_id"
    expect_status 200
    status=$(jq -r '.status' <<<"$HTTP_BODY")
    case $status in
      ok | partial | failed | skipped) printf '%s' "$HTTP_BODY"; return 0 ;;
    esac
    (( SECONDS < deadline )) || fail "任务 ${run_id} 轮询超时（${POLL_TIMEOUT}s），最后状态 ${status}"
    sleep "$POLL_INTERVAL"
  done
}

require_job_terminal() {
  local body=$1 what=$2 status
  status=$(jq -r '.status' <<<"$body")
  case $status in
    ok | partial | skipped) printf '%s' "$body" ;;
    *) fail "${what} 任务失败（status=${status}）：$(jq -r '.error // "无 error 字段"' <<<"$body")" ;;
  esac
}

# 统计某标的 confirm=true 的日线根数。
candles_confirmed_count() {
  local inst_id=$1 cursor="" body count=0 page
  while true; do
    local -a args=(-sS -G "$API_BASE/market/candles"
      --data-urlencode "inst_id=$inst_id"
      --data-urlencode "bar=1d"
      --data-urlencode "limit=300"
      -w $'\n%{http_code}')
    if [[ -n $cursor ]]; then args+=(--data-urlencode "cursor=$cursor"); fi
    body=$(curl "${args[@]}") || fail "读取 ${inst_id} K 线失败"
    HTTP_STATUS=${body##*$'\n'}
    HTTP_BODY=${body%$'\n'*}
    expect_status 200
    page=$(jq -r '[.items[] | select(.confirm == true)] | length' <<<"$HTTP_BODY")
    count=$(( count + page ))
    cursor=$(jq -r '.next_cursor // empty' <<<"$HTTP_BODY")
    [[ -n $cursor ]] || break
  done
  printf '%s' "$count"
}

# 回显某标的最后一个 confirm=true 日线的 open_time（升序分页取末条）。
candles_last_confirmed_day() {
  local inst_id=$1 cursor="" last="" body page
  while true; do
    local -a args=(-sS -G "$API_BASE/market/candles"
      --data-urlencode "inst_id=$inst_id"
      --data-urlencode "bar=1d"
      --data-urlencode "limit=300"
      -w $'\n%{http_code}')
    if [[ -n $cursor ]]; then args+=(--data-urlencode "cursor=$cursor"); fi
    body=$(curl "${args[@]}") || fail "读取 ${inst_id} K 线失败"
    HTTP_STATUS=${body##*$'\n'}
    HTTP_BODY=${body%$'\n'*}
    expect_status 200
    page=$(jq -r '[.items[] | select(.confirm == true) | .open_time] | last // empty' <<<"$HTTP_BODY")
    if [[ -n $page ]]; then last=$page; fi
    cursor=$(jq -r '.next_cursor // empty' <<<"$HTTP_BODY")
    [[ -n $cursor ]] || break
  done
  [[ -n $last ]] || fail "标的 ${inst_id} 没有已确认的日线"
  printf '%s' "$last"
}

shift_day() {
  local iso=$1 days=$2
  date -u -d "${iso} ${days} days" +%Y-%m-%dT00:00:00Z
}

# ---------------------------------------------------------------- 步骤 0

step_begin 0 "预检：六个容器健康、API /health、迁移版本"
docker compose -f "$COMPOSE_FILE" ps --format json >"$WORK_DIR/containers.jsonl" \
  || fail "读取 compose 容器状态失败（需要 docker 与运行中的 compose 栈）"
running=$(jq -r 'select(.State == "running") | .Service' <"$WORK_DIR/containers.jsonl" | sort | tr '\n' ' ')
healthy=$(jq -r 'select(.Health == "healthy") | .Service' <"$WORK_DIR/containers.jsonl" | sort | tr '\n' ' ')
for svc in api postgres redis scheduler web worker; do
  [[ " $running " == *" $svc "* ]] || fail "服务 ${svc} 未运行（running: ${running:-无}）"
  [[ " $healthy " == *" $svc "* ]] || fail "服务 ${svc} 未健康（healthy: ${healthy:-无}）"
done

health=$(curl -fsS "$API_ROOT/health") || fail "GET $API_ROOT/health 失败（API 未就绪）"
[[ $(jq -r '.status' <<<"$health") == "ok" ]] || fail "health 状态不是 ok：$health"

migration="skipped"
if [[ ${SKIP_MIGRATION_CHECK:-0} != "1" ]]; then
  migration=$(
    docker compose -f "$COMPOSE_FILE" exec -T api alembic current 2>/dev/null \
      | tr -d '\r' | sed -n '$p'
  ) || fail "读取 alembic current 失败（需要 docker 与运行中的 compose 栈）"
  [[ $migration == *"(head)"* ]] || fail "迁移版本不在 head：$migration"
fi
step_end 200 "6 容器 running+healthy；health=ok；迁移=${migration}"
ARTIFACT_ENTRIES+=("$(jq -n --arg m "$migration" --arg r "$running" '{migration:$m, running_services:$r}')")

# ---------------------------------------------------------------- 步骤 1

step_begin 1 "行情：POST /market/sync/instruments → 回补 1d 日线 → 读取 K 线"
http POST /market/sync/instruments '{}'
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "同步接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
sync_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.status' <<<"$HTTP_BODY") != "skipped" ]]; then
  require_job_terminal "$(poll_job "$sync_job")" "标的同步" >/dev/null
fi

instruments_file="$WORK_DIR/instruments.jsonl"
: >"$instruments_file"
cursor=""
while true; do
  http GET "/market/instruments?limit=200${cursor:+&cursor=$cursor}"
  expect_status 200
  jq -c '.items' <<<"$HTTP_BODY" >>"$instruments_file"
  cursor=$(jq -r '.next_cursor // empty' <<<"$HTTP_BODY")
  [[ -n $cursor ]] || break
done
instrument_total=$(jq -s 'add | length' "$instruments_file")
(( instrument_total > 0 )) || fail "标的列表为空"

mapfile -t backfill_insts < <(jq -rs 'add[] | select(.inst_category == 3) | .inst_id' "$instruments_file")
(( ${#backfill_insts[@]} > 0 )) || fail "没有 inst_category=3 的标的可回补"

declare -a backfill_jobs=()
reused=0
for inst in "${backfill_insts[@]}"; do
  payload=$(jq -n --arg i "$inst" --arg b "1d" --arg s "$E2E_START" --arg e "$E2E_END" \
    '{inst_id:$i, bar:$b, start:$s, end:$e}')
  http POST /market/backfill "$payload"
  [[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "回补 ${inst} 返回 HTTP $HTTP_STATUS：$HTTP_BODY"
  if [[ $HTTP_STATUS == 200 ]]; then reused=$(( reused + 1 )); fi
  backfill_jobs+=("$(jq -r '.job_id' <<<"$HTTP_BODY")")
done

declare -a failed_insts=()
for idx in "${!backfill_jobs[@]}"; do
  result=$(poll_job "${backfill_jobs[idx]}")
  case $(jq -r '.status' <<<"$result") in
    ok | partial | skipped) ;;
    *) failed_insts+=("${backfill_insts[idx]}") ;;
  esac
done

# OKX 上游偶发 5xx 会让单个任务 failed；failed 是允许重试的终态，补跑一轮。
retried=${#failed_insts[@]}
if (( retried > 0 )); then
  declare -a retry_jobs=()
  for inst in "${failed_insts[@]}"; do
    payload=$(jq -n --arg i "$inst" --arg b "1d" --arg s "$E2E_START" --arg e "$E2E_END" \
      '{inst_id:$i, bar:$b, start:$s, end:$e}')
    http POST /market/backfill "$payload"
    [[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "重试回补 ${inst} 返回 HTTP $HTTP_STATUS"
    retry_jobs+=("$(jq -r '.job_id' <<<"$HTTP_BODY")")
  done
  failed_insts=()
  for idx in "${!retry_jobs[@]}"; do
    result=$(poll_job "${retry_jobs[idx]}")
    case $(jq -r '.status' <<<"$result") in
      ok | partial | skipped) ;;
      *) failed_insts+=("${backfill_insts[idx]}") ;;
    esac
  done
fi
(( ${#failed_insts[@]} == 0 )) || fail "回补失败的标的：${failed_insts[*]}"

target_bars=$(candles_confirmed_count "${TARGET_SYMBOL}-USDT-SWAP")
(( target_bars >= 60 )) || fail "${TARGET_SYMBOL}-USDT-SWAP 只有 ${target_bars} 根已确认日线，少于 60"
LATEST_DAY=$(candles_last_confirmed_day "${TARGET_SYMBOL}-USDT-SWAP")
step_end "$HTTP_STATUS" "标的 ${instrument_total} 个；回补 ${#backfill_jobs[@]} 个任务（复用 ${reused}，重试 ${retried}）；${TARGET_SYMBOL} 日线 ${target_bars} 根，最新 ${LATEST_DAY}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson n "$instrument_total" --argjson j "${#backfill_jobs[@]}" \
  --argjson r "$retried" --argjson b "$target_bars" --arg d "$LATEST_DAY" \
  '{instrument_total:$n, backfill_jobs:$j, backfill_retried:$r, target_bars:$b, latest_day:$d}')")

# ---------------------------------------------------------------- 步骤 2

step_begin 2 "股票关系：POST /targets → 相关性重算 → relations → relative-strength"
http POST /targets "$(jq -n --arg s "$TARGET_SYMBOL" --arg e "$TARGET_EXCHANGE" '{symbol:$s, exchange:$e}')"
[[ $HTTP_STATUS == 201 || $HTTP_STATUS == 200 ]] || fail "创建目标返回 HTTP $HTTP_STATUS：$HTTP_BODY"
TARGET_ID=$(jq -r '.id' <<<"$HTTP_BODY")
target_code=$HTTP_STATUS

http POST "/targets/${TARGET_ID}/relations/recompute" \
  "$(jq -n --argjson w "$RELATION_WINDOW" --arg a "$LATEST_DAY" \
    '{window_bars:$w, method:"pearson", price_basis:"okx_close", as_of:$a}')"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "相关性重算返回 HTTP $HTTP_STATUS：$HTTP_BODY"
relation_code=$HTTP_STATUS
if [[ $(jq -r '.status' <<<"$HTTP_BODY") != "skipped" ]]; then
  require_job_terminal "$(poll_job "$(jq -r '.job_id' <<<"$HTTP_BODY")")" "相关性重算" >/dev/null
fi

http GET "/targets/${TARGET_ID}/relations"
expect_status 200
relations_body=$HTTP_BODY
edge_count=$(jq -r '.edges | length' <<<"$relations_body")
(( edge_count >= 1 )) || fail "相关性快照没有边（status=$(jq -r '.status' <<<"$relations_body")）"

RS_COUNTERPARTY=""
rs_ratio=""
rs_momentum=""
for cp in $(jq -r '.edges[].counterparty_inst_id' <<<"$relations_body" | head -25); do
  http GET "/targets/${TARGET_ID}/relative-strength?counterparty=${cp}&lookback=${RS_LOOKBACK}"
  expect_status 200
  [[ $(jq -r '.defined' <<<"$HTTP_BODY") == "true" ]] || continue
  candidate_ratio=$(jq -r '.rs_ratio' <<<"$HTTP_BODY")
  candidate_momentum=$(jq -r '.rs_momentum' <<<"$HTTP_BODY")
  if [[ $candidate_ratio != "null" && $candidate_momentum != "null" ]]; then
    RS_COUNTERPARTY=$cp
    rs_ratio=$candidate_ratio
    rs_momentum=$candidate_momentum
    break
  fi
done
[[ -n $RS_COUNTERPARTY ]] || fail "所有尝试的对手方都没有完整的 rs_ratio/rs_momentum"
step_end "$HTTP_STATUS" "target_id=${TARGET_ID}（HTTP ${target_code}）；边 ${edge_count} 条；RS 对手 ${RS_COUNTERPARTY}，rs_ratio=${rs_ratio}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson t "$TARGET_ID" --argjson e "$edge_count" --arg c "$RS_COUNTERPARTY" \
  --arg r "$rs_ratio" --arg m "$rs_momentum" \
  '{target_id:$t, relation_edges:$e, rs_counterparty:$c, rs_ratio:$r, rs_momentum:$m}')")

# ---------------------------------------------------------------- 步骤 3

step_begin 3 "全市场扫描：POST /opportunities/scan → GET /opportunities"
http POST /opportunities/scan '{}'
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "扫描接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
scan_code=$HTTP_STATUS
scan_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.status' <<<"$HTTP_BODY") != "skipped" ]]; then
  require_job_terminal "$(poll_job "$scan_job")" "全市场扫描" >/dev/null
fi

http GET "/opportunities?limit=200"
expect_status 200
opportunity_total=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( opportunity_total >= 1 )) || fail "最新扫描运行没有产出机会"
OPPORTUNITY_RUN=$(jq -r '.run_id' <<<"$HTTP_BODY")
step_end "$scan_code" "run_id=${OPPORTUNITY_RUN}，机会 ${opportunity_total} 条"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$OPPORTUNITY_RUN" --argjson n "$opportunity_total" \
  '{opportunity_run:$r, opportunity_count:$n}')")

# ---------------------------------------------------------------- 步骤 4

step_begin 4 "策略：POST /strategies（目标驱动）→ submit → approve"
http POST /strategies "$(jq -n --argjson t "$TARGET_ID" --arg n "$STRATEGY_NAME" --arg m "$STRATEGY_MARKER" \
  '{kind:"directional", name:$n, target_id:$t, templates:["directional"], params:{marker:$m}}')"
[[ $HTTP_STATUS == 201 || $HTTP_STATUS == 200 ]] || fail "创建策略返回 HTTP $HTTP_STATUS：$HTTP_BODY"
strategy_code=$HTTP_STATUS
STRATEGY_ID=$(jq -r '.id' <<<"$HTTP_BODY")
strategy_status=$(jq -r '.status' <<<"$HTTP_BODY")

case $strategy_status in
  draft | pending_approval | approved) ;;
  *) fail "策略状态异常：${strategy_status}" ;;
esac
if [[ $strategy_status == "draft" ]]; then
  http POST "/strategies/${STRATEGY_ID}/submit"
  expect_status 200
  [[ $(jq -r '.status' <<<"$HTTP_BODY") == "pending_approval" ]] || fail "submit 后状态异常：$HTTP_BODY"
  strategy_status="pending_approval"
fi
if [[ $strategy_status == "pending_approval" ]]; then
  http POST "/strategies/${STRATEGY_ID}/approve" '{"reviewer":"s12-full-smoke","note":"1.0 集成验收"}'
  expect_status 200
  [[ $(jq -r '.status' <<<"$HTTP_BODY") == "approved" ]] || fail "approve 后状态不是 approved：$HTTP_BODY"
  strategy_status="approved"
fi

http GET "/strategies/${STRATEGY_ID}"
expect_status 200
[[ $(jq -r '.status' <<<"$HTTP_BODY") == "approved" ]] || fail "GET 策略状态不是 approved：$HTTP_BODY"
leg_count=$(jq -r '.legs | length' <<<"$HTTP_BODY")
(( leg_count >= 2 )) || fail "策略只有 ${leg_count} 条腿"
mapfile -t leg_weights < <(jq -r '.legs[].weight' <<<"$HTTP_BODY")
weight_total=$(python3 -c 'import decimal,sys;print(sum((abs(decimal.Decimal(x)) for x in sys.argv[1:]), decimal.Decimal(0)))' "${leg_weights[@]}")
[[ $weight_total == "1.0000000000" ]] || fail "腿权重绝对值之和为 ${weight_total}，不等于 1"
step_end "$strategy_code" "strategy_id=${STRATEGY_ID}（HTTP ${strategy_code}），${leg_count} 条腿，Σ|w|=${weight_total}，status=approved"
ARTIFACT_ENTRIES+=("$(jq -n --argjson s "$STRATEGY_ID" --argjson l "$leg_count" --arg w "$weight_total" \
  '{strategy_id:$s, legs:$l, weight_sum:$w}')")

# ---------------------------------------------------------------- 步骤 5

step_begin 5 "历史回测：POST /backtests → metrics / equity / trades"
http GET "/strategies/${STRATEGY_ID}"
expect_status 200
mapfile -t leg_insts < <(jq -r '.legs[].inst_id' <<<"$HTTP_BODY")
(( ${#leg_insts[@]} >= 2 )) || fail "回测前置：GET /strategies/${STRATEGY_ID} 返回的腿数不足（${#leg_insts[@]}）"
win_end=""
for inst in "${leg_insts[@]}"; do
  day=$(candles_last_confirmed_day "$inst")
  if [[ -z $win_end || $day < $win_end ]]; then win_end=$day; fi
done
win_start=$(shift_day "$win_end" "-${BACKTEST_DAYS}")
win_end_exclusive=$(shift_day "$win_end" "+1")

http POST /backtests "$(jq -n --argjson s "$STRATEGY_ID" --arg ws "$win_start" --arg we "$win_end_exclusive" \
  '{strategy_id:$s, window:{start:$ws, end:$we, name:"s12-full-smoke", role:"eval"}, bar:"1d", initial_capital:"100000", cost_model:{taker_fee_bps:"5", maker_fee_bps:"2", slippage_bps:"1", funding_bps_per_period:"0", funding:true, fee_role:"taker"}}')"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "创建回测返回 HTTP $HTTP_STATUS：$HTTP_BODY"
backtest_code=$HTTP_STATUS
RUN_ID=$(jq -r '.run_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.dispatched' <<<"$HTTP_BODY") == "true" ]]; then
  require_job_terminal "$(poll_job "$(jq -r '.job_id' <<<"$HTTP_BODY")")" "历史回测" >/dev/null
fi

http GET "/backtests/${RUN_ID}"
expect_status 200
[[ $(jq -r '.status' <<<"$HTTP_BODY") == "ok" ]] || fail "回测状态不是 ok：$(jq -r '.error // ""' <<<"$HTTP_BODY")"

http GET "/backtests/${RUN_ID}/metrics"
expect_status 200
metric_count=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( metric_count == 10 )) || fail "指标项数为 ${metric_count}，不是 10"
total_return=$(jq -r '[.items[] | select(.name == "total_return")][0].value // "n/a"' <<<"$HTTP_BODY")
max_drawdown=$(jq -r '[.items[] | select(.name == "max_drawdown")][0].value // "n/a"' <<<"$HTTP_BODY")

http GET "/backtests/${RUN_ID}/equity?limit=200"
expect_status 200
equity_count=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( equity_count >= 1 )) || fail "净值曲线为空"

http GET "/backtests/${RUN_ID}/trades?limit=200"
expect_status 200
trade_count=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( trade_count >= 1 )) || fail "成交明细为空"
step_end "$backtest_code" "run_id=${RUN_ID}（HTTP ${backtest_code}），窗口 ${win_start} → ${win_end}，指标 ${metric_count}，净值点 ${equity_count}，成交 ${trade_count}，total_return=${total_return}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$RUN_ID" --argjson m "$metric_count" --argjson e "$equity_count" \
  --argjson t "$trade_count" --arg tr "$total_return" --arg dd "$max_drawdown" \
  '{backtest_run:$r, metrics:$m, equity_points:$e, trades:$t, total_return:$tr, max_drawdown:$dd}')")

# ---------------------------------------------------------------- 步骤 6

step_begin 6 "风控：收紧限额 → 超限 → 落库评估（幂等）→ 放行该策略"
http GET "/risk/policy?strategy_id=$STRATEGY_ID"
expect_status 200
base_version=$(jq -r '.version' <<<"$HTTP_BODY")

http PUT /risk/policy "$(jq -n --argjson v "$base_version" --argjson s "$STRATEGY_ID" '{
  expected_version: $v,
  updated_by: "s12-full-smoke",
  note: "1.0 集成验收：收紧限额以构造超限",
  strategy_id: $s,
  thresholds: {
    max_order_notional: "10000",
    max_leg_weight: "0.3",
    max_leverage: "0.5",
    max_gross_exposure: "0.5",
    max_net_exposure: "0.5",
    max_instrument_weight: "0.3",
    max_concentration: "0.3",
    drawdown_warn: "0.05",
    drawdown_reduce: "0.10",
    drawdown_close: "0.25",
    funding_rate_threshold: "0.0005",
    min_depth_notional: "20000"
  }
}')"
expect_status 200
tight_version=$(jq -r '.version' <<<"$HTTP_BODY")
(( tight_version > base_version )) || fail "限额版本未递增：${base_version} → ${tight_version}"

http GET "/risk/status?strategy_id=$STRATEGY_ID"
expect_status 200
[[ $(jq -r '.allowed' <<<"$HTTP_BODY") == "false" ]] || fail "收紧限额后仍放行：$HTTP_BODY"
breach_codes=$(jq -r '[.breaches[].code] | unique | join(",")' <<<"$HTTP_BODY")
[[ $breach_codes == *"gross_exposure_exceeded"* ]] || fail "未命中总敞口限额：${breach_codes}"

eval_payload=$(jq -n --argjson s "$STRATEGY_ID" --arg k "$EVALUATION_KEY" '{strategy_id:$s, evaluation_key:$k}')
http POST /risk/evaluate "$eval_payload"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "评估接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
evaluate_code=$HTTP_STATUS
evaluate_run=$(jq -r '.run_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.dispatched' <<<"$HTTP_BODY") == "true" ]]; then
  require_job_terminal "$(poll_job "$(jq -r '.job_id' <<<"$HTTP_BODY")")" "风控评估" >/dev/null
fi

http GET "/risk/events?strategy_id=${STRATEGY_ID}&kind=limit_breach&limit=100"
expect_status 200
limit_events=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( limit_events >= 1 )) || fail "未产生 limit_breach 事件"

http POST /risk/evaluate "$eval_payload"
[[ $HTTP_STATUS == 200 || $HTTP_STATUS == 202 ]] || fail "重复评估返回 HTTP $HTTP_STATUS"
[[ $(jq -r '.run_id' <<<"$HTTP_BODY") == "$evaluate_run" ]] || fail "重复评估未复用同一 run_id"
[[ $(jq -r '.created' <<<"$HTTP_BODY") == "false" ]] || fail "重复评估不应新建任务"

# 回测净值本身有回撤，本策略作用域放宽回撤阈值，让 paper 下单路径可用；
# 全局默认策略不变，真实交易仍由 REAL_TRADING_ENABLED 门禁关闭。
http PUT /risk/policy "$(jq -n --argjson v "$tight_version" --argjson s "$STRATEGY_ID" '{
  expected_version: $v,
  updated_by: "s12-full-smoke",
  note: "1.0 集成验收：该验收策略放宽到可执行，供 paper 下单路径验证",
  strategy_id: $s,
  thresholds: {
    max_order_notional: "500000",
    max_leg_weight: "1.0",
    max_leverage: "2.0",
    max_gross_exposure: "2.0",
    max_net_exposure: "2.0",
    max_instrument_weight: "1.0",
    max_concentration: "1.0",
    drawdown_warn: "0.95",
    drawdown_reduce: "0.98",
    drawdown_close: "0.99",
    funding_rate_threshold: "0.0005",
    min_depth_notional: "20000"
  }
}')"
expect_status 200
open_version=$(jq -r '.version' <<<"$HTTP_BODY")

http GET "/risk/status?strategy_id=$STRATEGY_ID"
expect_status 200
[[ $(jq -r '.allowed' <<<"$HTTP_BODY") == "true" ]] || fail "放宽后仍不放行：$HTTP_BODY"
step_end "$evaluate_code" "限额 v${base_version}→v${tight_version}→v${open_version}；命中：${breach_codes}；limit_breach 事件 ${limit_events} 条；放宽后 allowed=true"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$evaluate_run" --argjson n "$limit_events" --arg c "$breach_codes" \
  '{evaluate_run:$r, limit_breach_events:$n, breach_codes:$c}')")

# ---------------------------------------------------------------- 步骤 7

step_begin 7 "paper 执行：GET /execution/mode → 下单 → sync"
http GET /execution/mode
expect_status 200
mode=$(jq -r '.mode' <<<"$HTTP_BODY")
[[ $mode == "paper" ]] || fail "执行模式不是 paper：$mode"
real_enabled=$(jq -r '.real_trading_enabled' <<<"$HTTP_BODY")
[[ $real_enabled == "false" ]] || fail "REAL_TRADING_ENABLED 不是 false：${real_enabled}"

http GET "/execution/orders?strategy_id=${STRATEGY_ID}&limit=200"
expect_status 200
paper_before=$(jq -r '[.items[] | select(.mode == "paper")] | length' <<<"$HTTP_BODY")
order_existed=$(jq -r --arg k "$ORDER_CLIENT_ID" '[.items[] | select(.client_order_id == $k)] | length' <<<"$HTTP_BODY")

http GET "/strategies/${STRATEGY_ID}"
expect_status 200
ORDER_INST=$(jq -r '.legs[0].inst_id' <<<"$HTTP_BODY")
ORDER_POSITION_SIDE=$(jq -r '.legs[0].side' <<<"$HTTP_BODY")
case $ORDER_POSITION_SIDE in
  long) ORDER_SIDE=buy ;;
  short) ORDER_SIDE=sell ;;
  *) fail "腿方向异常：${ORDER_POSITION_SIDE}" ;;
esac

http POST /execution/paper/orders "$(jq -n --argjson s "$STRATEGY_ID" --arg i "$ORDER_INST" \
  --arg side "$ORDER_SIDE" --arg ps "$ORDER_POSITION_SIDE" --arg q "$ORDER_QUANTITY" --arg k "$ORDER_CLIENT_ID" \
  '{strategy_id:$s, inst_id:$i, side:$side, position_side:$ps, quantity:$q, order_type:"market", client_order_id:$k}')"
[[ $HTTP_STATUS == 201 || $HTTP_STATUS == 200 ]] || fail "paper 下单返回 HTTP $HTTP_STATUS：$HTTP_BODY"
order_code=$HTTP_STATUS
ORDER_ID=$(jq -r '.id' <<<"$HTTP_BODY")
[[ $(jq -r '.mode' <<<"$HTTP_BODY") == "paper" ]] || fail "订单 mode 不是 paper：$HTTP_BODY"

http POST "/execution/orders/${ORDER_ID}/sync"
[[ $HTTP_STATUS == 200 || $HTTP_STATUS == 201 ]] || fail "订单 sync 返回 HTTP $HTTP_STATUS：$HTTP_BODY"

http GET "/execution/orders?strategy_id=${STRATEGY_ID}&limit=200"
expect_status 200
paper_after=$(jq -r '[.items[] | select(.mode == "paper")] | length' <<<"$HTTP_BODY")
order_state=$(jq -r --arg i "$ORDER_ID" '[.items[] | select((.id|tostring) == $i)][0].state' <<<"$HTTP_BODY")
if [[ $order_existed == "0" ]]; then
  [[ $paper_after == "$(( paper_before + 1 ))" ]] || fail "paper 订单数未增加 1：${paper_before} → ${paper_after}"
else
  [[ $paper_after == "$paper_before" ]] || fail "重复执行叠加了 paper 订单：${paper_before} → ${paper_after}"
fi
step_end "$order_code" "mode=paper，real_trading_enabled=false；order_id=${ORDER_ID}（${ORDER_INST} ${ORDER_SIDE}/${ORDER_POSITION_SIDE} × ${ORDER_QUANTITY}）state=${order_state}；paper 订单 ${paper_before} → ${paper_after}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson o "$ORDER_ID" --arg s "$order_state" --argjson b "$paper_before" \
  --argjson a "$paper_after" '{paper_order:$o, paper_order_state:$s, paper_orders_before:$b, paper_orders_after:$a}')")

# ---------------------------------------------------------------- 步骤 8

step_begin 8 "MCP：只读客户端 → tools/call 与 REST 一致 → operate 越权 403"
http GET /mcp/clients
expect_status 200
for stale in $(jq -r --arg n "$MCP_CLIENT_NAME" \
  '[.items[] | select(.name == $n and .revoked_at == null)][].id' <<<"$HTTP_BODY"); do
  http DELETE "/mcp/clients/${stale}"
  expect_status 200
done

http POST /mcp/clients "$(jq -n --arg n "$MCP_CLIENT_NAME" '{name:$n, scopes:["read"]}')"
expect_status 201
MCP_CLIENT_ID=$(jq -r '.client.id' <<<"$HTTP_BODY")
MCP_TOKEN=$(jq -r '.token' <<<"$HTTP_BODY")
[[ ${#MCP_TOKEN} -ge 32 ]] || fail "创建 MCP 客户端未返回 token"

mcp_call "$MCP_TOKEN" "$(jq -n --argjson s "$STRATEGY_ID" \
  '{jsonrpc:"2.0", id:1, method:"tools/call", params:{name:"get_strategy", arguments:{strategy_id:$s}}}')"
expect_status 200
[[ $(jq -r '.result.isError // false' <<<"$HTTP_BODY") == "false" ]] || fail "MCP get_strategy 调用失败：$HTTP_BODY"
mcp_strategy=$(jq -r '.result.content[0].text' <<<"$HTTP_BODY" | jq .)
mcp_name=$(jq -r '.name' <<<"$mcp_strategy")
mcp_status=$(jq -r '.status' <<<"$mcp_strategy")

http GET "/strategies/${STRATEGY_ID}"
expect_status 200
[[ $(jq -r '.name' <<<"$HTTP_BODY") == "$mcp_name" ]] || fail "MCP 策略名与 REST 不一致：${mcp_name} ≠ $(jq -r '.name' <<<"$HTTP_BODY")"
[[ $(jq -r '.status' <<<"$HTTP_BODY") == "$mcp_status" ]] || fail "MCP 策略状态与 REST 不一致：${mcp_status} ≠ $(jq -r '.status' <<<"$HTTP_BODY")"

mcp_call "$MCP_TOKEN" "$(jq -n --arg k "${STRATEGY_MARKER}-forbidden-$EVALUATION_KEY" \
  '{jsonrpc:"2.0", id:2, method:"tools/call", params:{name:"trigger_scan", arguments:{reason:"越权探测", idempotency_key:$k}}}')"
[[ $HTTP_STATUS == 403 ]] || fail "read 客户端调用 operate 工具应 403，实际 $HTTP_STATUS：$HTTP_BODY"
[[ $(jq -r '.error.data.code' <<<"$HTTP_BODY") == "mcp_forbidden" ]] || fail "越权错误码不是 mcp_forbidden：$HTTP_BODY"

mcp_call "$MCP_TOKEN" '{"jsonrpc":"2.0","id":3,"method":"ping"}'
expect_status 200
step_end 200 "client_id=${MCP_CLIENT_ID}；get_strategy 与 REST 一致（name=${mcp_name}，status=${mcp_status}）；trigger_scan 越权 403 mcp_forbidden"
ARTIFACT_ENTRIES+=("$(jq -n --argjson c "$MCP_CLIENT_ID" --arg n "$mcp_name" --arg s "$mcp_status" \
  '{mcp_client:$c, mcp_strategy_name:$n, mcp_strategy_status:$s, mcp_operate_http:403}')")

# ---------------------------------------------------------------- 步骤 9

step_begin 9 "收尾：真实交易红线断言与关键 ID 汇总"
http GET /execution/mode
expect_status 200
[[ $(jq -r '.mode' <<<"$HTTP_BODY") == "paper" ]] || fail "收尾时执行模式不是 paper"
[[ $(jq -r '.real_trading_enabled' <<<"$HTTP_BODY") == "false" ]] || fail "收尾时 REAL_TRADING_ENABLED 不是 false"

http GET "/execution/orders?mode=real&limit=200"
expect_status 200
real_orders=$(jq -r '.items | length' <<<"$HTTP_BODY")
[[ $real_orders == "0" ]] || fail "存在 ${real_orders} 条 mode=real 订单，红线被突破"
step_end 200 "mode=paper，REAL_TRADING_ENABLED=false，mode=real 订单 ${real_orders} 条"
ARTIFACT_ENTRIES+=("$(jq -n --argjson n "$real_orders" '{real_mode_orders:$n}')")

# ---------------------------------------------------------------- 汇总

printf '\n%-4s %-52s %-6s %-9s %s\n' "步骤" "内容" "HTTP" "耗时(ms)" "结论"
for row in "${SUMMARY_ROWS[@]}"; do
  IFS='|' read -r n name code ms note <<<"$row"
  printf '%-4s %-52s %-6s %-9s %s\n' "$n" "$name" "$code" "$ms" "$note"
done

printf '\n关键 ID（人工复核用）：target=%s strategy=%s backtest_run=%s opportunity_run=%s paper_order=%s mcp_client=%s\n' \
  "$TARGET_ID" "$STRATEGY_ID" "$RUN_ID" "$OPPORTUNITY_RUN" "$ORDER_ID" "$MCP_CLIENT_ID"

mkdir -p "$(dirname "$ARTIFACT")"
printf '%s\n' "${ARTIFACT_ENTRIES[@]}" | jq -s \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg api "$API_BASE" --arg key "$EVALUATION_KEY" \
  '{generated_at:$ts, api_base:$api, evaluation_key:$key, steps:.}' >"$ARTIFACT" \
  || fail "写入验收产物失败：$ARTIFACT"
printf '\n验收产物：%s\n' "${ARTIFACT#"$REPO_ROOT"/}"
printf '全链路（步骤 0-9）通过。\n'
