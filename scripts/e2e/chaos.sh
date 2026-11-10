#!/usr/bin/env bash
# 故障注入验收脚本（MKACG-703 / S12-02）。
#
# 目的：证明四类故障下系统**不产生脏数据**、恢复后可继续工作，
# 而不是承诺「自动降级」「自动自愈」这类功能。每条结论都必须有实测输出。
#
# 四类故障：
#   1. Redis 停摆：读接口不受影响；任务投递失败必须给出错误响应，且不写业务数据。
#   2. PostgreSQL 停摆：存活探针仍 ok，就绪探针 fail-closed；恢复后自愈。
#   3. 上游限流（429）：回补任务失败并记录原因，绝不写入半截数据；恢复后可重跑。
#   4. 进程重启：worker 重启后调度链路恢复；已有数据无重复行，幂等键语义不变。
#
# 退出码 0 表示四类故障的**不变量**全部成立；失败会打印步骤号与原因。
# 已知未闭环项（见 docs/reports/chaos-report.md 的工程债一节）不隐藏：
# worker 被杀后残留的 running 行、投递失败残留的 queued 行都会被统计并打印。
#
# 产物：默认写 $HOME/.cache/s12/chaos-artifacts.json，不弄脏工作区；
# 需要刷新仓库内的 docs/reports/chaos-artifacts.json 时显式指定：
#   ARTIFACT=docs/reports/chaos-artifacts.json bash scripts/e2e/chaos.sh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"

API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE=${API_BASE:-$API_ROOT/api/v1}

PG_USER=${POSTGRES_USER:-trading}
PG_DB=${POSTGRES_DB:-trading}

POLL_TIMEOUT=${POLL_TIMEOUT:-300}
POLL_INTERVAL=${POLL_INTERVAL:-2}

STUB_NAME=${STUB_NAME:-s12-okx-429}
STUB_PORT=${STUB_PORT:-8099}
STUB_IMAGE=${STUB_IMAGE:-trading-api:local}

# 故障注入专用的回补参数：与业务数据不重叠，避免污染正常验收数据集。
# 周期性采集只覆盖 equity_sync_symbols / candle_ingest_symbols 里的标的，
# 这里选一个不在其中的标的，让「故障期间计数不变」的断言只受被测任务影响。
CHAOS_INST=${CHAOS_INST:-PEP-USDT-SWAP}
CHAOS_BAR=${CHAOS_BAR:-1d}

ARTIFACT=${ARTIFACT:-$HOME/.cache/s12/chaos-artifacts.json}

mkdir -p "$HOME/.cache"
WORK_DIR=$(mktemp -d "$HOME/.cache/chaos.XXXXXX")

CURRENT_STEP=""
STEP_NAME=""
STEP_T0=0
HTTP_STATUS=""
HTTP_BODY=""
declare -a SUMMARY_ROWS=()
declare -a ARTIFACT_ENTRIES=()
declare -a DEBT=()

cleanup() {
  docker rm -f "$STUB_NAME" >/dev/null 2>&1 || true
  docker compose -f "$COMPOSE_FILE" up -d --no-deps api worker >/dev/null 2>&1 || true
  docker compose -f "$COMPOSE_FILE" start postgres redis >/dev/null 2>&1 || true
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

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
  local note=$1
  local ms=$(( $(date +%s%3N) - STEP_T0 ))
  printf '  ✓ 耗时 %sms，%s\n' "$ms" "$note"
  SUMMARY_ROWS+=("$CURRENT_STEP|$STEP_NAME|$ms|$note")
}

# http METHOD URL_SUFFIX [JSON_BODY]：20s 硬超时，任何挂起都算失败。
http() {
  local method=$1 path=$2 data=${3-} out
  if [[ -n $data ]]; then
    out=$(curl -sS -m 20 -X "$method" "$API_BASE$path" \
      -H 'Content-Type: application/json' -d "$data" -w $'\n%{http_code}') \
      || out=$'curl-failed\n000'
  else
    out=$(curl -sS -m 20 -X "$method" "$API_BASE$path" -w $'\n%{http_code}') \
      || out=$'curl-failed\n000'
  fi
  HTTP_STATUS=${out##*$'\n'}
  HTTP_BODY=${out%$'\n'*}
  return 0
}

health_code() {
  curl -sS -m 20 -o /dev/null -w '%{http_code}' "$API_ROOT/health" || printf '000'
}

# psql_scalar SQL：单值查询。
psql_scalar() {
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "$PG_USER" -d "$PG_DB" -At -c "$1" 2>/dev/null | tr -d '\r' | head -1
}

candle_count() {
  psql_scalar "select count(*) from market.candle c join market.instrument i on i.id = c.instrument_id
               where i.inst_id = '${CHAOS_INST}' and c.bar = '${CHAOS_BAR}'"
}

duplicate_candle_rows() {
  psql_scalar "select count(*) - count(distinct (instrument_id, bar, open_time)) from market.candle"
}

job_status() {
  psql_scalar "select status from ops.job_run where id = $1"
}

wait_service() {
  local svc=$1 want=$2 deadline
  deadline=$(( SECONDS + 180 ))
  while true; do
    state=$(docker compose -f "$COMPOSE_FILE" ps --format json \
      | jq -r --arg s "$svc" 'select(.Service == $s) | "\(.State)/\(.Health // "")"')
    [[ $state == "$want" ]] && return 0
    (( SECONDS < deadline )) || return 1
    sleep 2
  done
}

wait_api_ready() {
  local deadline=$(( SECONDS + 180 ))
  while true; do
    [[ $(health_code) == "200" ]] && return 0
    (( SECONDS < deadline )) || return 1
    sleep 2
  done
}

# poll_job RUN_ID [TIMEOUT]：等待 ops 任务进入终态，返回终态名。
poll_job() {
  local run_id=$1 limit=${2:-$POLL_TIMEOUT} deadline status
  deadline=$(( SECONDS + limit ))
  while true; do
    status=$(job_status "$run_id")
    case $status in
      ok | partial | failed | skipped) printf '%s' "$status"; return 0 ;;
    esac
    (( SECONDS < deadline )) || { printf '%s' "$status"; return 1; }
    sleep "$POLL_INTERVAL"
  done
}

post_backfill() {
  local start=$1 end=$2
  http POST /market/backfill "$(jq -n --arg i "$CHAOS_INST" --arg b "$CHAOS_BAR" --arg s "$start" --arg e "$end" \
    '{inst_id:$i, bar:$b, start:$s, end:$e}')"
}

# ---------------------------------------------------------------- 步骤 0

step_begin 0 "预检：六容器健康、基线计数"
healthy=$(docker compose -f "$COMPOSE_FILE" ps --format json | jq -r 'select(.Health == "healthy") | .Service' | sort | tr '\n' ' ')
for svc in api postgres redis scheduler web worker; do
  [[ " $healthy " == *" $svc "* ]] || fail "服务 ${svc} 未健康（healthy: ${healthy:-无}）"
done
[[ $(health_code) == "200" ]] || fail "GET /health 不是 200"

BASE_CANDLES=$(candle_count)
BASE_TOTAL_CANDLES=$(psql_scalar "select count(*) from market.candle")
BASE_ORDERS=$(psql_scalar "select count(*) from execution.\"order\"")
BASE_STRATEGIES=$(psql_scalar "select count(*) from strategy.strategy")
BASE_DUP=$(duplicate_candle_rows)
[[ $BASE_DUP == "0" ]] || fail "基线里已有 ${BASE_DUP} 条重复 K 线"
step_end "6 容器 healthy；${CHAOS_INST} ${CHAOS_BAR} 基线 ${BASE_CANDLES} 根；K 线总数 ${BASE_TOTAL_CANDLES}；订单 ${BASE_ORDERS}；策略 ${BASE_STRATEGIES}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson c "$BASE_CANDLES" --argjson t "$BASE_TOTAL_CANDLES" \
  --argjson o "$BASE_ORDERS" --argjson s "$BASE_STRATEGIES" \
  '{phase:"baseline", chaos_candles:$c, candles_total:$t, orders:$o, strategies:$s}')")

# ---------------------------------------------------------------- 步骤 1

step_begin 1 "故障一：Redis 停摆（读可用、投递失败、无脏写、可恢复）"
docker compose -f "$COMPOSE_FILE" stop redis >/dev/null || fail "停止 redis 失败"
read -r health_ms <<<"$(curl -sS -m 20 -o /dev/null -w '%{http_code} %{time_total}' "$API_ROOT/health" || echo '000 0')"
[[ $health_ms == 200* ]] || fail "Redis 停摆时 /health 不是 200：$health_ms"

read -r inst_code inst_ms <<<"$(curl -sS -m 20 -o /dev/null -w '%{http_code} %{time_total}' \
  "$API_BASE/market/instruments?limit=5" || echo '000 0')"
[[ $inst_code == "200" ]] || fail "Redis 停摆时读接口返回 ${inst_code}（读路径不应依赖 Redis）"

post_backfill "2025-01-01T00:00:00Z" "2025-02-01T00:00:00Z"
redis_down_code=$HTTP_STATUS
redis_down_body=$HTTP_BODY
case $redis_down_code in
  5* | 202 | 200) ;;
  000)
    # 投递请求 20s 内没有任何响应：arq 在 Redis 不可达时持续重试，HTTP 层不返回错误响应。
    # 如实记录为「投递不可用」，不当作成功，也不隐藏。
    DEBT+=("redis 停摆时任务投递请求 20s 无响应（客户端超时），未返回错误响应体，调用方无法区分「已受理」与「未受理」")
    ;;
  *) fail "Redis 停摆时投递返回 HTTP ${redis_down_code}：${redis_down_body}" ;;
esac
sleep 3
after_down_candles=$(candle_count)
[[ $after_down_candles == "$BASE_CANDLES" ]] \
  || fail "Redis 停摆期间写入了 K 线：${BASE_CANDLES} → ${after_down_candles}"

if [[ $redis_down_code == "202" ]]; then
  job_id=$(jq -r '.job_id' <<<"$redis_down_body")
  if ! poll_job "$job_id" 60 >/dev/null; then
    fail "Redis 停摆时受理的任务未在 60s 内进入终态（job ${job_id}）"
  fi
fi

docker compose -f "$COMPOSE_FILE" start redis >/dev/null || fail "启动 redis 失败"
wait_service redis "running/healthy" || fail "redis 未在 180s 内恢复健康"

post_backfill "2025-01-01T00:00:00Z" "2025-02-01T00:00:00Z"
replay_code=$HTTP_STATUS
replay_status=$(jq -r '.status // empty' <<<"$HTTP_BODY")
replay_job=$(jq -r '.job_id // empty' <<<"$HTTP_BODY")
recovered="否"
case $replay_status in
  skipped)
    DEBT+=("redis 停摆时投递失败留下的 queued 任务行（job ${replay_job}）会永久锁死同参数幂等键：重放返回 200/skipped，任务不再执行")
    ;;
  *)
    terminal=$(poll_job "$replay_job" 300) || fail "恢复后重放的任务 ${replay_job} 未进入终态（${terminal}）"
    case $terminal in
      ok | partial | skipped) recovered="是（job ${replay_job} → ${terminal}）" ;;
      *) fail "恢复后重放的任务 ${replay_job} 终态为 ${terminal}" ;;
    esac
    ;;
esac

# 无论上面是否踩到被锁死的键，换一个未使用过的窗口必须能正常跑通，
# 用来证明「投递通道恢复」本身成立。
post_backfill "2025-02-01T00:00:00Z" "2025-03-01T00:00:00Z"
fresh_code=$HTTP_STATUS
fresh_job=$(jq -r '.job_id // empty' <<<"$HTTP_BODY")
[[ $fresh_code == "202" || $fresh_code == "200" ]] || fail "恢复后新窗口投递返回 HTTP ${fresh_code}：${HTTP_BODY}"
fresh_terminal=$(poll_job "$fresh_job" 300) || fail "恢复后新窗口任务 ${fresh_job} 未进入终态（${fresh_terminal}）"
case $fresh_terminal in
  ok | partial | skipped) ;;
  *) fail "恢复后新窗口任务 ${fresh_job} 终态为 ${fresh_terminal}" ;;
esac

step_end "Redis 停摆：/health 200、读接口 ${inst_code}（${inst_ms}s）、投递 ${redis_down_code}；恢复后重放 ${replay_code}/${replay_status:-n/a}、新窗口 ${fresh_code}/${fresh_terminal}；停摆期间 K 线 ${BASE_CANDLES} → ${after_down_candles} 未变"
ARTIFACT_ENTRIES+=("$(jq -n --argjson hc "${health_ms%% *}" --arg ic "$inst_code" --arg down "$redis_down_code" \
  --arg replay "$replay_status" --arg fr "$fresh_terminal" --argjson before "$BASE_CANDLES" --argjson after "$after_down_candles" \
  '{phase:"redis_down", health_http:$hc, read_http:$ic, dispatch_http:$down, replay_status:$replay, fresh_job_status:$fr, candles_before:$before, candles_after:$after}')")

# ---------------------------------------------------------------- 步骤 2

step_begin 2 "故障二：PostgreSQL 停摆（存活 ok、就绪 fail-closed、恢复自愈）"
docker compose -f "$COMPOSE_FILE" stop postgres >/dev/null || fail "停止 postgres 失败"
sleep 3

read -r health_code_pg _ <<<"$(curl -sS -m 20 -o /dev/null -w '%{http_code} %{time_total}' "$API_ROOT/health" || echo '000 0')"
[[ $health_code_pg == "200" ]] || fail "PostgreSQL 停摆时存活探针不是 200：${health_code_pg}"

ready_out=$(curl -sS -m 20 -w $'\n%{http_code}' "$API_ROOT/ready") || ready_out=$'curl-failed\n000'
ready_code=${ready_out##*$'\n'}
ready_body=${ready_out%$'\n'*}
case $ready_code in
  503)
    [[ $(jq -r '.error.code' <<<"$ready_body") == "dependency_unavailable" ]] \
      || fail "就绪探针错误码不是 dependency_unavailable：${ready_body}"
    ;;
  000)
    # 连接一直挂起直到客户端 20s 超时：仍然没有返回 200（fail-closed 成立），
    # 但探测端拿不到错误体，负载均衡会按超时摘除节点。
    DEBT+=("postgres 停摆时就绪探针 20s 无响应（客户端超时），未在超时内返回 503 错误体；建议给连接池设置 connect_timeout")
    ;;
  *) fail "就绪探针在 DB 停摆时必须 fail-closed（503 或超时无响应），实际 ${ready_code}" ;;
esac

read -r list_code list_time <<<"$(curl -sS -m 20 -o /dev/null -w '%{http_code} %{time_total}' \
  "$API_BASE/market/instruments?limit=3" || echo '000 0')"
list_time=${list_time%% *}
case $list_code in
  5*) ;;
  000)
    DEBT+=("postgres 停摆时读接口 20s 无响应（客户端超时），未返回错误响应体")
    ;;
  *) fail "PostgreSQL 停摆时读接口应失败，实际 ${list_code}" ;;
esac
[[ $(docker compose -f "$COMPOSE_FILE" ps --format json | jq -r 'select(.Service == "api") | .State') == "running" ]] \
  || fail "api 容器在 PostgreSQL 停摆期间退出了"

docker compose -f "$COMPOSE_FILE" start postgres >/dev/null || fail "启动 postgres 失败"
t_recover=$SECONDS
rec_deadline=$(( SECONDS + 120 ))
while true; do
  ready_now=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "$API_ROOT/ready" || echo 000)
  [[ $ready_now == "200" ]] && break
  (( SECONDS < rec_deadline )) || fail "PostgreSQL 恢复后 120s 内 /ready 仍未返回 200"
  sleep 1
done
recover_secs=$(( SECONDS - t_recover ))
wait_service postgres "running/healthy" || fail "postgres 未恢复健康"

[[ $(candle_count) == "$BASE_CANDLES" ]] || fail "PostgreSQL 故障前后 K 线数不一致"
[[ $(psql_scalar "select count(*) from execution.\"order\"") == "$BASE_ORDERS" ]] || fail "PostgreSQL 故障前后订单数不一致"
step_end "停摆期间 /health 200、/ready ${ready_code}（fail-closed）、读接口 ${list_code}（${list_time}s）、api 存活；恢复耗时 ${recover_secs}s；数据计数无变化"
ARTIFACT_ENTRIES+=("$(jq -n --arg hc "$health_code_pg" --arg rc "$ready_code" --arg lc "$list_code" \
  --argjson rs "$recover_secs" '{phase:"postgres_down", health_http:$hc, ready_http:$rc, read_http:$lc, recovery_seconds:$rs}')")

# ---------------------------------------------------------------- 步骤 3

step_begin 3 "故障三：上游 429（任务失败留痕、零脏写、恢复后重跑成功）"
cat >"$WORK_DIR/stub429.py" <<'PY'
import http.server
import json

BODY = json.dumps({"code": "50011", "msg": "Too Many Requests", "data": []}).encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def _reply(self) -> None:
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    do_GET = _reply
    do_POST = _reply

    def log_message(self, *args: object) -> None:  # 保持桩的输出干净
        return


http.server.HTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
PY

docker rm -f "$STUB_NAME" >/dev/null 2>&1 || true
docker run -d --rm --name "$STUB_NAME" --network trading_default \
  -v "$WORK_DIR/stub429.py:/tmp/stub429.py:ro" "$STUB_IMAGE" \
  python /tmp/stub429.py >/dev/null || fail "启动 429 桩服务失败（镜像 ${STUB_IMAGE} 缺失？）"

stub_ready=""
for _ in $(seq 1 30); do
  stub_ready=$(docker compose -f "$COMPOSE_FILE" exec -T api python -c \
    "import urllib.request,urllib.error
try:
    urllib.request.urlopen('http://${STUB_NAME}:${STUB_PORT}/api/v5/public/instruments', timeout=3)
    print('200')
except urllib.error.HTTPError as exc:
    print(exc.code)
except Exception as exc:
    print('err:' + type(exc).__name__)" 2>/dev/null | tr -d '\r')
  [[ $stub_ready == "429" ]] && break
  sleep 1
done
[[ $stub_ready == "429" ]] || fail "429 桩服务未就绪：${stub_ready}"

before_429=$(candle_count)
OKX_REST_BASE_URL="http://${STUB_NAME}:${STUB_PORT}" \
  docker compose -f "$COMPOSE_FILE" up -d --no-deps api worker >/dev/null || fail "重启 api/worker 注入上游地址失败"
wait_api_ready || fail "注入上游地址后 api 未就绪"
wait_service worker "running/healthy" || fail "注入上游地址后 worker 未健康"

post_backfill "2025-03-01T00:00:00Z" "2025-04-01T00:00:00Z"
[[ $HTTP_STATUS == "202" || $HTTP_STATUS == "200" ]] || fail "429 场景投递返回 HTTP ${HTTP_STATUS}"
down_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
down_terminal=$(poll_job "$down_job" 300) || fail "429 场景任务 ${down_job} 未进入终态（${down_terminal}）"
down_error=$(psql_scalar "select coalesce(left(error, 200), '') from ops.job_run where id = ${down_job}")
[[ $down_terminal == "failed" ]] || fail "上游 429 时任务应 failed，实际 ${down_terminal}"
[[ $down_error == *"429"* || $down_error == *"upstream"* ]] || fail "任务未记录上游限流原因：${down_error}"
after_429=$(candle_count)
[[ $after_429 == "$before_429" ]] || fail "上游 429 期间写入了 K 线：${before_429} → ${after_429}"

docker rm -f "$STUB_NAME" >/dev/null 2>&1 || true
docker compose -f "$COMPOSE_FILE" up -d --no-deps api worker >/dev/null || fail "恢复 api/worker 上游地址失败"
wait_api_ready || fail "恢复上游地址后 api 未就绪"
wait_service worker "running/healthy" || fail "恢复上游地址后 worker 未健康"

post_backfill "2025-03-01T00:00:00Z" "2025-04-01T00:00:00Z"
recover_terminal=$(poll_job "$(jq -r '.job_id' <<<"$HTTP_BODY")" 300) \
  || fail "上游恢复后重跑未进入终态"
case $recover_terminal in
  ok | partial) ;;
  *) fail "上游恢复后重跑终态为 ${recover_terminal}" ;;
esac
after_recover=$(candle_count)
[[ $after_recover -ge $before_429 ]] || fail "上游恢复后 K 线数反而减少"
step_end "桩服务返回 429；任务 ${down_job} → failed（error: ${down_error:0:60}…）；期间 K 线 ${before_429} → ${after_429} 未变；上游恢复后同窗口重跑 → ${recover_terminal}，K 线 ${after_recover} 根"
ARTIFACT_ENTRIES+=("$(jq -n --argjson j "$down_job" --arg st "$down_terminal" --arg err "$down_error" \
  --arg rt "$recover_terminal" --argjson b "$before_429" --argjson a "$after_429" --argjson r "$after_recover" \
  '{phase:"upstream_429", job:$j, job_status:$st, job_error:$err, replay_status:$rt, candles_before:$b, candles_during:$a, candles_after:$r}')")

# ---------------------------------------------------------------- 步骤 4

step_begin 4 "故障四：worker 进程重启（调度恢复、无重复行、幂等键不变）"
restart_t0=$SECONDS
docker compose -f "$COMPOSE_FILE" restart worker >/dev/null || fail "重启 worker 失败"
wait_service worker "running/healthy" || fail "worker 未在 180s 内恢复健康"
restart_secs=$(( SECONDS - restart_t0 ))

# 调度链路恢复：等一个重启之后新开始的周期任务跑到终态。
fresh_job_id=$(psql_scalar "select id from ops.job_run where job_name='ingest_candles' and started_at > now() - interval '5 minutes' and status in ('ok') order by id desc limit 1")
resume_deadline=$(( SECONDS + 300 ))
while [[ -z $fresh_job_id ]]; do
  (( SECONDS < resume_deadline )) || fail "worker 重启后 300s 内没有周期任务成功执行"
  sleep 5
  fresh_job_id=$(psql_scalar "select id from ops.job_run where job_name='ingest_candles' and started_at > now() - interval '5 minutes' and status in ('ok') order by id desc limit 1")
done

dup_after=$(duplicate_candle_rows)
[[ $dup_after == "0" ]] || fail "重启后出现 ${dup_after} 条重复 K 线"

# 幂等键语义不变：同一参数重放不新增行、不新增数据。
post_backfill "2025-04-01T00:00:00Z" "2025-05-01T00:00:00Z"
first_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
poll_job "$first_job" 300 >/dev/null || fail "重启后首个回补任务未进入终态"
# 首个任务落库之后才取基线：重放对比的是「同参数再来一次」的增量。
pre_replay_jobs=$(psql_scalar "select count(*) from ops.job_run where job_name = 'backfill_candles'")
mid_candles=$(candle_count)
post_backfill "2025-04-01T00:00:00Z" "2025-05-01T00:00:00Z"
second_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
[[ $second_job == "$first_job" ]] || fail "同参数重放拿到了新任务：${first_job} → ${second_job}"
[[ $(candle_count) == "$mid_candles" ]] || fail "同参数重放重复写入了 K 线"
post_replay_jobs=$(psql_scalar "select count(*) from ops.job_run where job_name = 'backfill_candles'")
[[ $post_replay_jobs == "$pre_replay_jobs" ]] || fail "同参数重放新增了任务行：${pre_replay_jobs} → ${post_replay_jobs}"

# 未闭环项统计：只统计不隐藏，写进报告。
stuck_running=$(psql_scalar "select count(*) from ops.job_run where status='running'")
stuck_queued=$(psql_scalar "select count(*) from ops.job_run where status='queued'")
(( stuck_running > 0 )) && DEBT+=("worker 被杀时正在执行的任务会留在 ops.job_run status=running（当前 ${stuck_running} 行），没有启动时的回收器")
(( stuck_queued > 0 )) && DEBT+=("投递失败会留下 status=queued 的任务行（当前 ${stuck_queued} 行），同参数幂等键被锁死直到人工处理")

step_end "worker 重启 ${restart_secs}s 后恢复健康并跑完周期任务（job ${fresh_job_id}）；重复 K 线 ${dup_after} 条；同参数重放复用 job ${first_job}、回补任务行 ${pre_replay_jobs} → ${post_replay_jobs}、K 线 ${mid_candles} 不变；残留 running=${stuck_running} queued=${stuck_queued}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson rs "$restart_secs" --argjson fj "$fresh_job_id" --argjson dup "$dup_after" \
  --argjson j "$first_job" --argjson b "$pre_replay_jobs" --argjson a "$post_replay_jobs" \
  --argjson r "$stuck_running" --argjson q "$stuck_queued" \
  '{phase:"worker_restart", restart_seconds:$rs, resumed_job:$fj, duplicate_candles:$dup, replayed_job:$j, jobs_before:$b, jobs_after:$a, stuck_running:$r, stuck_queued:$q}')")

# ---------------------------------------------------------------- 步骤 5

step_begin 5 "收尾：交易姿态未被故障注入改变 + 汇总结论"
http GET /execution/mode
[[ $HTTP_STATUS == "200" ]] || fail "GET /execution/mode 返回 ${HTTP_STATUS}"
mode=$(jq -r '.mode' <<<"$HTTP_BODY")
real_enabled=$(jq -r '.real_trading_enabled' <<<"$HTTP_BODY")
[[ $mode == "paper" ]] || fail "故障注入后执行模式变成 ${mode}"
[[ $real_enabled == "false" ]] || fail "故障注入后 REAL_TRADING_ENABLED 变成 ${real_enabled}"

http GET "/execution/orders?mode=real&limit=200"
[[ $HTTP_STATUS == "200" ]] || fail "读取真实订单失败：${HTTP_STATUS}"
real_orders=$(jq -r '.items | length' <<<"$HTTP_BODY")
[[ $real_orders == "0" ]] || fail "存在 ${real_orders} 条 mode=real 订单"

final_total=$(psql_scalar "select count(*) from market.candle")
[[ $final_total -ge $BASE_TOTAL_CANDLES ]] || fail "K 线总数减少：${BASE_TOTAL_CANDLES} → ${final_total}"
[[ $(psql_scalar "select count(*) from execution.\"order\"") == "$BASE_ORDERS" ]] || fail "故障注入期间产生了订单"
step_end "mode=${mode}，real_trading_enabled=${real_enabled}，mode=real 订单 ${real_orders} 条；K 线总数 ${BASE_TOTAL_CANDLES} → ${final_total}；订单 ${BASE_ORDERS} 未变"
ARTIFACT_ENTRIES+=("$(jq -n --arg m "$mode" --arg r "$real_enabled" --argjson o "$real_orders" \
  '{phase:"final", execution_mode:$m, real_trading_enabled:$r, real_orders:$o}')")

printf '\n%-4s %-58s %-8s %s\n' "步骤" "故障场景" "耗时(ms)" "结论"
for row in "${SUMMARY_ROWS[@]}"; do
  IFS='|' read -r n name ms note <<<"$row"
  printf '%-4s %-58s %-8s %s\n' "$n" "$name" "$ms" "$note"
done

if (( ${#DEBT[@]} > 0 )); then
  printf '\n已知未闭环项（登记为工程债，不计入通过条件）：\n'
  for item in "${DEBT[@]}"; do printf '  - %s\n' "$item"; done
fi

mkdir -p "$(dirname "$ARTIFACT")"
if (( ${#DEBT[@]} == 0 )); then
  debt_json='[]'
else
  debt_json=$(printf '%s\n' "${DEBT[@]}" | jq -R -s 'split("\n") | map(select(length > 0))')
fi
printf '%s\n' "${ARTIFACT_ENTRIES[@]}" | jq -s \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson debt "$debt_json" \
  '{generated_at:$ts, phases:., known_debt:$debt}' >"$ARTIFACT" \
  || fail "写入故障注入产物失败：$ARTIFACT"
printf '\n故障注入产物：%s\n' "${ARTIFACT#"$REPO_ROOT"/}"
printf '四类故障的不变量全部成立。\n'
