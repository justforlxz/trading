#!/usr/bin/env bash
# P1 阶段一键验收脚本（MKACG-699 / P1-21）。
#
# 目标链：行情同步 → K 线回补 → 目标登记 → 相关性重算 → 相对强弱 →
#         全市场扫描 → 策略生成 → 审批 → 历史回测 → 报告页。
#
# 约束（见 docs/architecture/api-contract.md）：
#   * 只通过 HTTP 调用 API，不 import 后端模块、不直连数据库；
#     唯一例外是步骤 0 用 `docker compose exec` 读取 alembic 版本。
#   * 所有异步任务都以轮询 `GET /ops/job-runs/{id}` 等待终态，不用固定 sleep。
#   * 每一步独立可复跑：请求参数由数据推导且在同一天内确定，
#     因此重复执行时服务端按 job_key / strategy_key / run_key 命中幂等分支返回 200。
#
# 退出码：0 = 全部步骤通过；非 0 = 某一步失败（标准错误会打印失败步骤名）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE=${API_BASE:-$API_ROOT/api/v1}
WEB_BASE=${WEB_BASE:-http://localhost:5173}

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

ARTIFACT=${ARTIFACT:-$REPO_ROOT/docs/reports/p1-smoke-artifacts.json}

# 脚本自建的临时目录（只用于累积分页结果，退出时删除本目录）。
mkdir -p "$HOME/.cache"
WORK_DIR=$(mktemp -d "$HOME/.cache/p1-smoke.XXXXXX")
trap 'rm -rf -- "$WORK_DIR"' EXIT

CURRENT_STEP=""
STEP_NAME=""
STEP_T0=0
HTTP_STATUS=""
HTTP_BODY=""
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
    if ! out=$(curl -sS -X "$method" "$API_BASE$path" \
      -H 'Content-Type: application/json' -d "$data" -w $'\n%{http_code}'); then
      fail "请求失败：$method $API_BASE$path"
    fi
  else
    if ! out=$(curl -sS -X "$method" "$API_BASE$path" -w $'\n%{http_code}'); then
      fail "请求失败：$method $API_BASE$path"
    fi
  fi
  HTTP_STATUS=${out##*$'\n'}
  HTTP_BODY=${out%$'\n'*}
  return 0
}

expect_status() {
  local expected=$1
  shift
  [[ $HTTP_STATUS == "$expected" ]] || fail "期望 HTTP $expected，实际 $HTTP_STATUS；响应：$HTTP_BODY"
}

# 轮询业务任务到终态，结果 JSON 打印到标准输出。
poll_job() {
  local run_id=$1 deadline status body
  deadline=$(( SECONDS + POLL_TIMEOUT ))
  while true; do
    http GET "/ops/job-runs/$run_id"
    expect_status 200
    body=$HTTP_BODY
    status=$(jq -r '.status' <<<"$body")
    case $status in
      ok | partial | failed | skipped) printf '%s' "$body"; return 0 ;;
    esac
    (( SECONDS < deadline )) || fail "任务 ${run_id} 轮询超时（${POLL_TIMEOUT}s），最后状态 ${status}"
    sleep "$POLL_INTERVAL"
  done
}

# 要求任务终态可接受（ok / partial / skipped），返回任务结果 JSON。
require_job_terminal() {
  local body=$1 what=$2 status
  status=$(jq -r '.status' <<<"$body")
  case $status in
    ok | partial | skipped) printf '%s' "$body" ;;
    *) fail "${what} 任务失败（status=${status}）：$(jq -r '.error // "无 error 字段"' <<<"$body")" ;;
  esac
}

# 分页读取某标的的日线，回显最后一个 confirm=true 的 open_time。
candles_last_confirmed_day() {
  local inst_id=$1 cursor="" body last=""
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
    local page_last
    page_last=$(jq -r '[.items[] | select(.confirm == true)] | last | .open_time // empty' <<<"$HTTP_BODY")
    if [[ -n $page_last ]]; then last=$page_last; fi
    cursor=$(jq -r '.next_cursor // empty' <<<"$HTTP_BODY")
    [[ -n $cursor ]] || break
  done
  [[ -n $last ]] || fail "标的 ${inst_id} 没有已确认的日线"
  printf '%s' "$last"
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

# 把 ISO-8601 时间加减天数（UTC，输出 ...T00:00:00Z）。
shift_day() {
  local iso=$1 days=$2
  date -u -d "${iso} ${days} days" +%Y-%m-%dT00:00:00Z
}

# ---------------------------------------------------------------- 步骤 0

step_begin 0 "预检：API / Web 健康与数据库迁移版本"
health=$(curl -fsS "$API_ROOT/health") || fail "GET $API_ROOT/health 失败（API 未就绪）"
[[ $(jq -r '.status' <<<"$health") == "ok" ]] || fail "health 状态不是 ok：$health"
web_code=$(curl -sS -o /dev/null -w '%{http_code}' "$WEB_BASE/") || fail "GET $WEB_BASE/ 失败（Web 未就绪）"
[[ $web_code == "200" ]] || fail "Web 首页返回 HTTP $web_code"

migration="skipped"
if [[ ${SKIP_MIGRATION_CHECK:-0} != "1" ]]; then
  if ! migration=$(
    docker compose -f "$REPO_ROOT/infra/docker-compose.yml" exec -T api alembic current 2>/dev/null \
      | tr -d '\r' | tail -n 1
  ); then
    fail "读取 alembic current 失败（需要 docker 与运行中的 compose 栈）"
  fi
  [[ $migration == *"0006"* ]] || fail "迁移版本不是 0006：$migration"
fi
step_end "$web_code" "API health=ok；迁移=$migration"
ARTIFACT_ENTRIES+=("$(jq -n --arg m "$migration" --arg w "$web_code" '{migration:$m, web_status:$w}')")

# ---------------------------------------------------------------- 步骤 1

step_begin 1 "标的同步：POST /market/sync/instruments"
http POST /market/sync/instruments '{}'
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "同步接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
sync_body=$HTTP_BODY
sync_job=$(jq -r '.job_id' <<<"$sync_body")
sync_status=$(jq -r '.status' <<<"$sync_body")
if [[ $sync_status != "skipped" ]]; then
  sync_result=$(require_job_terminal "$(poll_job "$sync_job")" "标的同步")
  [[ $(jq -r '.status' <<<"$sync_result") != "failed" ]] || fail "标的同步任务失败"
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
has_googl=$(jq -s --arg i "${TARGET_SYMBOL}-USDT-SWAP" 'add | map(.inst_id) | index($i) != null' "$instruments_file")
(( instrument_total > 200 )) || fail "标的数量 ${instrument_total} 不足 200"
[[ $has_googl == "true" ]] || fail "标的中缺少 ${TARGET_SYMBOL}-USDT-SWAP"
step_end "$HTTP_STATUS" "标的 ${instrument_total} 个，含 ${TARGET_SYMBOL}-USDT-SWAP；任务 ${sync_job} 状态 ${sync_status}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson n "$instrument_total" '{instrument_total:$n}')")

# ---------------------------------------------------------------- 步骤 2

step_begin 2 "K 线回补：逐个 inst_category=3 标的 POST /market/backfill（bar=1d）"
mapfile -t backfill_insts < <(jq -rs 'add[] | select(.inst_category == 3) | .inst_id' "$instruments_file")
(( ${#backfill_insts[@]} > 0 )) || fail "没有 inst_category=3 的标的可回补"

declare -a backfill_jobs=()
since_200=0
for inst in "${backfill_insts[@]}"; do
  payload=$(jq -n --arg i "$inst" --arg b "1d" --arg s "$E2E_START" --arg e "$E2E_END" \
    '{inst_id:$i, bar:$b, start:$s, end:$e}')
  http POST /market/backfill "$payload"
  [[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "回补 ${inst} 返回 HTTP $HTTP_STATUS：$HTTP_BODY"
  if [[ $HTTP_STATUS == 200 ]]; then since_200=$(( since_200 + 1 )); fi
  backfill_jobs+=("$(jq -r '.job_id' <<<"$HTTP_BODY")")
done

ok_count=0
bad_count=0
declare -a failed_insts=()
for idx in "${!backfill_jobs[@]}"; do
  result=$(poll_job "${backfill_jobs[idx]}")
  case $(jq -r '.status' <<<"$result") in
    ok | partial | skipped) ok_count=$(( ok_count + 1 )) ;;
    *)
      bad_count=$(( bad_count + 1 ))
      failed_insts+=("${backfill_insts[idx]}")
      ;;
  esac
done

# OKX 上游偶发 5xx 会让单个任务 failed；failed 是同键可重试状态，补跑一轮。
retried=${#failed_insts[@]}
if (( retried > 0 )); then
  declare -a retry_jobs=()
  for inst in "${failed_insts[@]}"; do
    payload=$(jq -n --arg i "$inst" --arg b "1d" --arg s "$E2E_START" --arg e "$E2E_END" \
      '{inst_id:$i, bar:$b, start:$s, end:$e}')
    http POST /market/backfill "$payload"
    [[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "重试回补 ${inst} 返回 HTTP $HTTP_STATUS：$HTTP_BODY"
    retry_jobs+=("$(jq -r '.job_id' <<<"$HTTP_BODY")")
  done
  ok_count=0
  bad_count=0
  for job in "${retry_jobs[@]}"; do
    result=$(poll_job "$job")
    case $(jq -r '.status' <<<"$result") in
      ok | partial | skipped) ok_count=$(( ok_count + 1 )) ;;
      *) bad_count=$(( bad_count + 1 )) ;;
    esac
  done
  ok_count=$(( ok_count + ${#backfill_jobs[@]} - retried ))
fi

googl_bars=$(candles_confirmed_count "${TARGET_SYMBOL}-USDT-SWAP")
(( googl_bars >= 60 )) || fail "${TARGET_SYMBOL}-USDT-SWAP 只有 ${googl_bars} 根已确认日线，少于 60"
LATEST_DAY=$(candles_last_confirmed_day "${TARGET_SYMBOL}-USDT-SWAP")
step_end "$HTTP_STATUS" "回补 ${#backfill_jobs[@]} 个任务（成功 ${ok_count}，失败 ${bad_count}，复用 ${since_200}，重试 ${retried}）；${TARGET_SYMBOL} 日线 ${googl_bars} 根，最新 ${LATEST_DAY}"
(( bad_count == 0 )) || fail "有 ${bad_count} 个回补任务失败"
ARTIFACT_ENTRIES+=("$(jq -n --argjson total "${#backfill_jobs[@]}" --argjson ok "$ok_count" --argjson r "$retried" --argjson b "$googl_bars" --arg d "$LATEST_DAY" '{backfill_jobs:$total, backfill_ok:$ok, backfill_retried:$r, googl_bars:$b, latest_day:$d}')")

# ---------------------------------------------------------------- 步骤 3

step_begin 3 "目标登记：POST /targets"
http POST /targets "$(jq -n --arg s "$TARGET_SYMBOL" --arg e "$TARGET_EXCHANGE" '{symbol:$s, exchange:$e}')"
[[ $HTTP_STATUS == 201 || $HTTP_STATUS == 200 ]] || fail "创建目标返回 HTTP $HTTP_STATUS：$HTTP_BODY"
TARGET_ID=$(jq -r '.id' <<<"$HTTP_BODY")
target_instrument=$(jq -r '.instrument_id // empty' <<<"$HTTP_BODY")
target_code=$HTTP_STATUS

http GET /targets
expect_status 200
listed=$(jq -r --arg t "$TARGET_ID" '[.items[] | select((.id|tostring) == $t)] | length' <<<"$HTTP_BODY")
(( listed == 1 )) || fail "GET /targets 未包含目标 ${TARGET_ID}"
step_end "$target_code" "target_id=${TARGET_ID}（首次 201 / 复用 200 → 实际 ${target_code}）"
ARTIFACT_ENTRIES+=("$(jq -n --argjson id "$TARGET_ID" --arg code "$target_code" '{target_id:$id, target_http:$code}')")

# ---------------------------------------------------------------- 步骤 4

step_begin 4 "相关性重算：POST /targets/{id}/relations/recompute"
http POST "/targets/${TARGET_ID}/relations/recompute" \
  "$(jq -n --argjson w "$RELATION_WINDOW" --arg a "$LATEST_DAY" \
    '{window_bars:$w, method:"pearson", price_basis:"okx_close", as_of:$a}')"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "相关性重算返回 HTTP $HTTP_STATUS：$HTTP_BODY"
relation_code=$HTTP_STATUS
relation_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.status' <<<"$HTTP_BODY") != "skipped" ]]; then
  require_job_terminal "$(poll_job "$relation_job")" "相关性重算" >/dev/null
fi

http GET "/targets/${TARGET_ID}/relations"
expect_status 200
relations_body=$HTTP_BODY
edge_count=$(jq -r '.edges | length' <<<"$relations_body")
(( edge_count >= 1 )) || fail "相关性快照没有边（status=$(jq -r '.status' <<<"$relations_body")）：$relations_body"
bad_edges=$(jq -r '[.edges[] | select((has("coefficient") and has("best_lag") and has("stability")) | not)] | length' <<<"$relations_body")
(( bad_edges == 0 )) || fail "有 ${bad_edges} 条边缺少 coefficient/best_lag/stability"
COUNTERPARTY=$(jq -r '.edges[0].counterparty_inst_id' <<<"$relations_body")
COUNTERPARTY_SYMBOL=$(jq -r '.edges[0].counterparty.symbol' <<<"$relations_body")
snapshot_size=$(jq -r '.snapshot.sample_size // 0' <<<"$relations_body")
step_end "$relation_code" "边 ${edge_count} 条，sample_size=${snapshot_size}，首选对手 ${COUNTERPARTY_SYMBOL}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson n "$edge_count" --arg c "$COUNTERPARTY" --arg code "$relation_code" '{relation_edges:$n, counterparty:$c, relation_http:$code}')")

# ---------------------------------------------------------------- 步骤 5

step_begin 5 "相对强弱：GET /targets/{id}/relative-strength"
mapfile -t edge_counterparties < <(jq -r '.edges[].counterparty_inst_id' <<<"$relations_body")
rs_ok=""
rs_ratio=""
rs_momentum=""
rs_attempts=0
for cp in "${edge_counterparties[@]:0:25}"; do
  rs_attempts=$(( rs_attempts + 1 ))
  http GET "/targets/${TARGET_ID}/relative-strength?counterparty=${cp}&lookback=${RS_LOOKBACK}"
  expect_status 200
  [[ $(jq -r '.defined' <<<"$HTTP_BODY") == "true" ]] || continue
  candidate_ratio=$(jq -r '.rs_ratio' <<<"$HTTP_BODY")
  candidate_momentum=$(jq -r '.rs_momentum' <<<"$HTTP_BODY")
  if [[ $candidate_ratio != "null" && $candidate_momentum != "null" ]]; then
    COUNTERPARTY=$cp
    rs_ratio=$candidate_ratio
    rs_momentum=$candidate_momentum
    rs_ok=1
    break
  fi
done
[[ -n $rs_ok ]] || fail "所有尝试的对手方都没有完整的 rs_ratio/rs_momentum（尝试 ${rs_attempts} 个）"
COUNTERPARTY_SYMBOL=$(jq -r --arg i "$COUNTERPARTY" \
  '[.edges[] | select(.counterparty_inst_id == $i)][0].counterparty.symbol' <<<"$relations_body")
step_end "$HTTP_STATUS" "对手 ${COUNTERPARTY_SYMBOL}（尝试 ${rs_attempts} 个），rs_ratio=${rs_ratio}，rs_momentum=${rs_momentum}"
ARTIFACT_ENTRIES+=("$(jq -n --arg c "$COUNTERPARTY" --arg r "$rs_ratio" --arg m "$rs_momentum" \
  '{rs_counterparty:$c, rs_ratio:$r, rs_momentum:$m}')")

# ---------------------------------------------------------------- 步骤 6

step_begin 6 "全市场扫描：POST /opportunities/scan"
http POST /opportunities/scan '{}'
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "扫描接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
scan_code=$HTTP_STATUS
scan_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.status' <<<"$HTTP_BODY") != "skipped" ]]; then
  scan_result=$(require_job_terminal "$(poll_job "$scan_job")" "全市场扫描")
  scan_run_id=$(jq -r '.result.run_id // empty' <<<"$scan_result")
fi

http GET "/opportunities?limit=200"
expect_status 200
opportunity_total=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( opportunity_total >= 1 )) || fail "最新扫描运行没有产出机会：$HTTP_BODY"
opportunity_run=$(jq -r '.run_id' <<<"$HTTP_BODY")
step_end "$scan_code" "run_id=${opportunity_run}，机会 ${opportunity_total} 条"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$opportunity_run" --argjson n "$opportunity_total" '{opportunity_run:$r, opportunity_count:$n}')")

# ---------------------------------------------------------------- 步骤 7

step_begin 7 "策略生成：POST /strategies（目标驱动，失败回退机会驱动）"
strategy_source="target"
http POST /strategies "$(jq -n --argjson t "$TARGET_ID" \
  '{kind:"directional", name:"p1-smoke target strategy", target_id:$t, templates:["directional"], params:{}}')"
strategy_code=$HTTP_STATUS
strategy_body=$HTTP_BODY
if [[ $HTTP_STATUS == 422 ]]; then
  printf '  目标策略被拒（%s），回退机会驱动\n' "$(jq -r '.error.code // "unknown"' <<<"$HTTP_BODY")"
  strategy_source="opportunity"
  http GET "/opportunities?limit=200"
  expect_status 200
  opp_pick=$(jq -c '[.items[] | select(.kind == "relative_value")][0] // .items[0]' <<<"$HTTP_BODY")
  OPP_ID=$(jq -r '.id' <<<"$opp_pick")
  OPP_KIND=$(jq -r '.kind' <<<"$opp_pick")
  http POST /strategies "$(jq -n --arg k "$OPP_KIND" --argjson o "$OPP_ID" \
    '{kind:$k, name:"p1-smoke opportunity strategy", templates:[$k], params:{opportunity_id:$o}}')"
  strategy_code=$HTTP_STATUS
  strategy_body=$HTTP_BODY
fi
[[ $strategy_code == 201 || $strategy_code == 200 ]] || fail "创建策略返回 HTTP $strategy_code：$strategy_body"
STRATEGY_ID=$(jq -r '.id' <<<"$strategy_body")
strategy_status=$(jq -r '.status' <<<"$strategy_body")
case $strategy_status in
  draft | pending_approval | approved) ;;
  archived)
    fail "策略 ${STRATEGY_ID} 已归档（archived），同参数复跑无法复用：归档策略不能 submit，也不能回测。请先重建策略（改 params 生成新的 strategy_key），或清理该归档策略后重跑"
    ;;
  *) fail "策略状态异常：${strategy_status}" ;;
esac

mapfile -t weights < <(jq -r '.legs[].weight' <<<"$strategy_body")
weight_total=$(python3 -c 'import decimal,sys;print(sum((abs(decimal.Decimal(x)) for x in sys.argv[1:]), decimal.Decimal(0)))' "${weights[@]}")
[[ $weight_total == "1.0000000000" ]] || fail "腿权重绝对值之和为 ${weight_total}，不等于 1"
leg_count=$(jq -r '.legs | length' <<<"$strategy_body")
step_end "$strategy_code" "strategy_id=${STRATEGY_ID}（来源 ${strategy_source}，HTTP ${strategy_code}），kind=$(jq -r '.kind' <<<"$strategy_body")，${leg_count} 条腿，Σ|w|=${weight_total}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson id "$STRATEGY_ID" --arg code "$strategy_code" --arg src "$strategy_source" --argjson legs "$leg_count" --arg w "$weight_total" '{strategy_id:$id, strategy_http:$code, strategy_source:$src, legs:$legs, weight_sum:$w}')")

# ---------------------------------------------------------------- 步骤 8

step_begin 8 "人工审批：submit → approve"
if [[ $strategy_status == "draft" ]]; then
  http POST "/strategies/${STRATEGY_ID}/submit"
  expect_status 200
  [[ $(jq -r '.status' <<<"$HTTP_BODY") == "pending_approval" ]] || fail "submit 后状态不是 pending_approval：$HTTP_BODY"
  strategy_status="pending_approval"
fi
if [[ $strategy_status == "pending_approval" ]]; then
  http POST "/strategies/${STRATEGY_ID}/approve" '{"reviewer":"p1-smoke","note":"P1 阶段验收"}'
  expect_status 200
  [[ $(jq -r '.status' <<<"$HTTP_BODY") == "approved" ]] || fail "approve 后状态不是 approved：$HTTP_BODY"
  approval_note="draft→pending_approval→approved"
else
  approval_note="策略已是 approved（同参数复跑复用），跳过状态迁移"
fi
step_end "$HTTP_STATUS" "策略 ${STRATEGY_ID} → approved；${approval_note}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson id "$STRATEGY_ID" --arg n "$approval_note" '{approved_strategy:$id, approval_path:$n}')")

# ---------------------------------------------------------------- 步骤 9

step_begin 9 "历史回测：POST /backtests → 轮询 → metrics/equity/trades"
mapfile -t leg_insts < <(jq -r '.legs[].inst_id' <<<"$strategy_body")
win_end=""
for inst in "${leg_insts[@]}"; do
  day=$(candles_last_confirmed_day "$inst")
  if [[ -z $win_end || $day < $win_end ]]; then win_end=$day; fi
done
[[ -n $win_end ]] || fail "无法确定回测窗口结束日"
win_start=$(shift_day "$win_end" "-${BACKTEST_DAYS}")
win_end_exclusive=$(shift_day "$win_end" "+1")

http POST /backtests "$(jq -n --argjson s "$STRATEGY_ID" --arg ws "$win_start" --arg we "$win_end_exclusive" \
  '{strategy_id:$s, window:{start:$ws, end:$we, name:"p1-smoke", role:"eval"}, bar:"1d", initial_capital:"100000", cost_model:{taker_fee_bps:"5", maker_fee_bps:"2", slippage_bps:"1", funding_bps_per_period:"0", funding:true, fee_role:"taker"}}')"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "创建回测返回 HTTP $HTTP_STATUS：$HTTP_BODY"
backtest_code=$HTTP_STATUS
RUN_ID=$(jq -r '.run_id' <<<"$HTTP_BODY")
backtest_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.dispatched' <<<"$HTTP_BODY") == "true" ]]; then
  require_job_terminal "$(poll_job "$backtest_job")" "历史回测" >/dev/null
fi

http GET "/backtests/${RUN_ID}"
expect_status 200
run_status=$(jq -r '.status' <<<"$HTTP_BODY")
[[ $run_status == "ok" ]] || fail "回测状态为 ${run_status}：$(jq -r '.error // ""' <<<"$HTTP_BODY")"

http GET "/backtests/${RUN_ID}/metrics"
expect_status 200
metric_count=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( metric_count == 10 )) || fail "指标项数为 ${metric_count}，不是 10"

http GET "/backtests/${RUN_ID}/equity?limit=200"
expect_status 200
equity_count=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( equity_count >= 1 )) || fail "净值曲线为空"

http GET "/backtests/${RUN_ID}/trades?limit=200"
expect_status 200
trade_count=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( trade_count >= 1 )) || fail "成交明细为空"

total_return=$(
  http GET "/backtests/${RUN_ID}/metrics"
  jq -r '[.items[] | select(.name == "total_return")][0].value // "n/a"' <<<"$HTTP_BODY"
)
step_end "$backtest_code" "run_id=${RUN_ID}（HTTP ${backtest_code}），窗口 ${win_start} → ${win_end}，指标 ${metric_count}，净值点 ${equity_count}，成交 ${trade_count}，total_return=${total_return}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson id "$RUN_ID" --arg code "$backtest_code" --argjson m "$metric_count" --argjson e "$equity_count" --argjson t "$trade_count" --arg ws "$win_start" --arg we "$win_end" --arg tr "$total_return" '{backtest_run:$id, backtest_http:$code, metrics:$m, equity_points:$e, trades:$t, window_start:$ws, window_end:$we, total_return:$tr}')")

# ---------------------------------------------------------------- 步骤 10

step_begin 10 "报告页：GET \$WEB_BASE/backtests/{run_id}"
page=$(curl -sS -w $'\n%{http_code}' "$WEB_BASE/backtests/${RUN_ID}") || fail "访问报告页失败"
page_code=${page##*$'\n'}
page_body=${page%$'\n'*}
[[ $page_code == "200" ]] || fail "报告页返回 HTTP ${page_code}"
[[ $page_body == *"<title>trading</title>"* ]] || fail "报告页没有返回前端壳（缺少 <title>trading</title>）"
step_end "$page_code" "前端 SPA 路由可直达回测报告"
ARTIFACT_ENTRIES+=("$(jq -n --arg code "$page_code" --argjson id "$RUN_ID" '{report_page_http:$code, report_page_run:$id}')")

# ---------------------------------------------------------------- 步骤 11

step_begin 11 "输出汇总"
printf '\n%-4s %-44s %-6s %-9s %s\n' "步骤" "内容" "HTTP" "耗时(ms)" "结论"
for row in "${SUMMARY_ROWS[@]}"; do
  IFS='|' read -r n name code ms note <<<"$row"
  printf '%-4s %-44s %-6s %-9s %s\n' "$n" "$name" "$code" "$ms" "$note"
done

mkdir -p "$(dirname "$ARTIFACT")"
printf '%s\n' "${ARTIFACT_ENTRIES[@]}" | jq -s \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg api "$API_BASE" --arg web "$WEB_BASE" \
  '{generated_at:$ts, api_base:$api, web_base:$web, steps:.}' >"$ARTIFACT" \
  || fail "写入验收产物失败：$ARTIFACT"
printf '\n验收产物：%s\n' "$ARTIFACT"
step_end 200 "全链路通过，产物已写入 ${ARTIFACT#"$REPO_ROOT"/}"
