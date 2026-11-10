#!/usr/bin/env bash
# 安全审计探针（MKACG-703 / S12-04）
# 只做只读探测与受控操作：不创建真实订单，不写业务数据（允许项的写只有 MCP 客户端与 mcp_call_log）。
# 安全门禁：开跑前先确认部署处于 paper + REAL_TRADING_ENABLED=false，否则立即中止，不发任何下单请求。
# 退出码：全部断言通过为 0；任一断言不符（含姿态门禁不成立）为 1。
# 用法：bash scripts/e2e/security_audit.sh [--output <文件>]
set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"
API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE="$API_ROOT/api/v1"
CLIENT_NAME=${CLIENT_NAME:-s12-security-audit}
OUT=${OUT:-$HOME/.cache/s12/security.out}

FAILS=0

fail() {
  printf 'FAIL: %s\n' "$*"
  FAILS=$((FAILS + 1))
}

check() { # check <断言名> <期望> <实际>
  local name=$1 want=$2 got=$3
  if [[ $want == "$got" ]]; then
    printf '  ok   %s = %s\n' "$name" "$got"
  else
    fail "$name 期望 [$want] 实际 [$got]"
  fi
}

check_present() { # check_present <断言名> <值>
  local name=$1 got=$2
  if [[ -n $got && $got != null ]]; then
    printf '  ok   %s = %s\n' "$name" "$got"
  else
    fail "$name 为空"
  fi
}

jqv() { # jqv <jq 表达式> <json>
  jq -r "$1" <<<"$2" 2>/dev/null || true
}

psql_q() {
  docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U trading -d trading -At -c "$1"
}

req() { # req METHOD URL [BODY] [AUTH]
  local m=$1 u=$2 body=${3-} auth=${4-} out
  local hdr=(-H 'Content-Type: application/json')
  [[ -n $auth ]] && hdr+=(-H "Authorization: Bearer $auth")
  if [[ -n $body ]]; then
    out=$(curl -sS -m 20 -X "$m" "$u" "${hdr[@]}" -d "$body" -w $'\n%{http_code}')
  else
    out=$(curl -sS -m 20 -X "$m" "$u" "${hdr[@]}" -w $'\n%{http_code}')
  fi
  CODE=${out##*$'\n'}
  BODY=${out%$'\n'*}
}

main() {
  mkdir -p "$(dirname -- "$OUT")"
  exec > >(tee "$OUT") 2>&1

  # ---------------------------------------------------------------- P. 姿态门禁
  echo "=== P. 投产姿态前置门禁 ==="
  req GET "$API_BASE/execution/mode" "" ""
  check 'GET /execution/mode HTTP' 200 "$CODE"
  local pre_mode pre_real
  pre_mode=$(jqv '.mode' "$BODY")
  pre_real=$(jqv '.real_trading_enabled' "$BODY")
  check 'execution.mode' paper "$pre_mode"
  check 'real_trading_enabled' false "$pre_real"
  if (( FAILS > 0 )); then
    echo '致命：当前部署不是 paper + REAL_TRADING_ENABLED=false。'
    echo '本脚本后面会请求 POST /execution/orders（真实下单端点）以验证 403 门禁；'
    echo '在实盘态执行会真的向交易所下单，因此已在此中止，未发送任何下单请求。'
    echo '如需审计实盘部署，请先只在只读段（A/C）单独取证，不要复用本脚本。'
    return 1
  fi

  local strategy_id=${STRATEGY_ID:-$(psql_q 'select min(id) from strategy.strategy')}
  if [[ ! $strategy_id =~ ^[0-9]+$ ]]; then
    fail "找不到可用的 strategy_id（库中无策略）；请先跑 full_smoke.sh 或显式传 STRATEGY_ID"
    return 1
  fi
  echo "使用 strategy_id=$strategy_id"

  # ---------------------------------------------------------------- A. MCP 令牌
  echo
  echo '=== A. MCP 令牌鉴权 ==='
  CLIENT=$(curl -sS -m 20 -X POST "$API_BASE/mcp/clients" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$CLIENT_NAME\",\"scopes\":[\"read\"]}")
  TOK=$(jqv '.token' "$CLIENT")
  CID=$(jqv '.client.id' "$CLIENT")
  check_present 'POST /mcp/clients 返回 token' "$TOK"
  check_present 'POST /mcp/clients 返回 client.id' "$CID"
  if (( FAILS > 0 )); then
    return 1
  fi
  echo "client_id=$CID token_len=${#TOK} token_prefix=${TOK:0:4}..."

  CALL_READ="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"get_strategy\",\"arguments\":{\"strategy_id\":$strategy_id}}}"
  CALL_OP='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"trigger_scan","arguments":{"reason":"security-audit","idempotency_key":"s12-security-audit"}}}'
  BAD_TOKEN='invalid-token-for-audit'

  local token_hash plaintext_hits
  token_hash=$(psql_q "select token_hash from mcp.mcp_clients where id=$CID")
  plaintext_hits=$(psql_q "select count(*) from mcp.mcp_clients where token_hash='$TOK'")
  check 'token_hash 长度（sha256 十六进制）' 64 "${#token_hash}"
  [[ $token_hash =~ ^[0-9a-f]+$ ]] || fail "token_hash 不是十六进制：$token_hash"
  check '数据库中以明文令牌存的客户端数' 0 "$plaintext_hits"

  req POST "$API_ROOT/mcp" "$CALL_READ" ""
  echo "A1 无令牌 -> $CODE  $BODY"
  check 'A1 无令牌 HTTP' 401 "$CODE"
  check 'A1 错误码' mcp_unauthorized "$(jqv '.error.code' "$BODY")"

  req POST "$API_ROOT/mcp" "$CALL_READ" "$BAD_TOKEN"
  echo "A2 错误令牌 -> $CODE  $BODY"
  check 'A2 错误令牌 HTTP' 401 "$CODE"
  check 'A2 错误码' mcp_unauthorized "$(jqv '.error.code' "$BODY")"

  req POST "$API_ROOT/mcp" "$CALL_READ" "$TOK"
  echo "A3 正确令牌 -> $CODE"
  check 'A3 正确令牌 HTTP' 200 "$CODE"
  check 'A3 不是工具错误' false "$(jqv '.result.isError // false' "$BODY")"
  check_present 'A3 返回策略名' "$(jqv '.result.content[0].text' "$BODY" | jq -r '.name // empty' 2>/dev/null)"

  local before_strategy before_scan before_log after_strategy after_scan after_log latest_denied
  before_strategy=$(psql_q 'select count(*) from strategy.strategy')
  before_scan=$(psql_q "select count(*) from ops.job_run where job_name='scan_opportunities'")
  before_log=$(psql_q 'select count(*) from mcp.mcp_call_log')
  req POST "$API_ROOT/mcp" "$CALL_OP" "$TOK"
  echo "A4 read 令牌调 operate 工具 -> $CODE  $BODY"
  check 'A4 越权 HTTP' 403 "$CODE"
  check 'A4 JSON-RPC 错误码' -32003 "$(jqv '.error.code' "$BODY")"
  check 'A4 业务错误码' mcp_forbidden "$(jqv '.error.data.code' "$BODY")"
  after_strategy=$(psql_q 'select count(*) from strategy.strategy')
  after_scan=$(psql_q "select count(*) from ops.job_run where job_name='scan_opportunities'")
  after_log=$(psql_q 'select count(*) from mcp.mcp_call_log')
  echo "A4 越权前后：strategy.strategy $before_strategy -> $after_strategy；scan_opportunities 任务 $before_scan -> $after_scan；mcp_call_log $before_log -> $after_log"
  check 'A4 越权未创建策略' "$before_strategy" "$after_strategy"
  check 'A4 越权未派发扫描任务' "$before_scan" "$after_scan"
  check 'A4 只新增 1 条调用审计' "$((before_log + 1))" "$after_log"
  latest_denied=$(psql_q "select status || '/' || coalesce(error_code, '') from mcp.mcp_call_log where tool='trigger_scan' order by id desc limit 1")
  check 'A4 审计行标记被拒' denied/mcp_forbidden "$latest_denied"

  req DELETE "$API_BASE/mcp/clients/$CID" "" ""
  echo "A5 吊销客户端 -> $CODE  $BODY"
  check 'A5 吊销 HTTP' 200 "$CODE"
  check_present 'A5 revoked_at 已写入' "$(jqv '.revoked_at' "$BODY")"

  req POST "$API_ROOT/mcp" "$CALL_READ" "$TOK"
  echo "A6 吊销后同令牌 -> $CODE  $BODY"
  check 'A6 吊销后 HTTP' 401 "$CODE"
  check 'A6 吊销后错误码' mcp_unauthorized "$(jqv '.error.code' "$BODY")"

  # ---------------------------------------------------------------- B. 真实交易门禁
  echo
  echo '=== B. 真实交易门禁 ==='
  req GET "$API_BASE/execution/mode" "" ""
  echo "B1 GET /execution/mode -> $CODE  $BODY"
  check 'B1 HTTP' 200 "$CODE"
  check 'B1 execution.mode' paper "$(jqv '.mode' "$BODY")"
  check 'B1 real_trading_enabled' false "$(jqv '.real_trading_enabled' "$BODY")"
  if (( FAILS > 0 )); then
    echo '致命：下单前复核发现姿态已变化（不是 paper + REAL_TRADING_ENABLED=false），跳过后面的下单请求。'
    return 1
  fi

  req POST "$API_BASE/execution/orders" "" ""
  echo "B2 空请求体 POST /execution/orders -> $CODE  $BODY"
  check 'B2 HTTP' 403 "$CODE"
  check 'B2 错误码' real_trading_disabled "$(jqv '.error.code' "$BODY")"

  req POST "$API_BASE/execution/orders" \
    "{\"strategy_id\":$strategy_id,\"inst_id\":\"AAPL-USDT-SWAP\",\"side\":\"buy\",\"position_side\":\"long\",\"quantity\":\"1\"}" ""
  echo "B3 完整请求体 POST /execution/orders -> $CODE  $BODY"
  check 'B3 HTTP' 403 "$CODE"
  check 'B3 错误码' real_trading_disabled "$(jqv '.error.code' "$BODY")"

  local real_orders order_modes
  real_orders=$(psql_q "select count(*) from execution.\"order\" where mode='real'")
  order_modes=$(psql_q 'select distinct mode from execution."order"' | paste -sd'|' -)
  echo "B4 mode=real 订单数: $real_orders"
  echo "B5 全部订单按 mode 分布: $(psql_q 'select mode, count(*) from execution."order" group by 1' | paste -sd'|' -)"
  check 'B4 mode=real 订单数' 0 "$real_orders"
  if [[ -n $order_modes ]]; then
    check 'B5 订单 mode 只有 paper' paper "$order_modes"
  fi

  # ---------------------------------------------------------------- C. 凭据与配置面
  echo
  echo '=== C. 凭据与配置面 ==='
  local ak sk pk real_enabled tok_hits secret_hits
  ak=$(docker compose -f "$COMPOSE_FILE" exec -T api python -c \
    'from app.config import get_settings as g; print(len(g().okx_api_key))')
  sk=$(docker compose -f "$COMPOSE_FILE" exec -T api python -c \
    'from app.config import get_settings as g; print(len(g().okx_api_secret))')
  pk=$(docker compose -f "$COMPOSE_FILE" exec -T api python -c \
    'from app.config import get_settings as g; print(len(g().okx_api_passphrase))')
  real_enabled=$(docker compose -f "$COMPOSE_FILE" exec -T api python -c \
    'from app.config import get_settings as g; print(g().real_trading_enabled)')
  echo "C1 容器内 OKX 凭据长度: api_key $ak secret $sk passphrase $pk"
  echo "C2 REAL_TRADING_ENABLED: $real_enabled"
  check 'C1 容器内 OKX api_key 长度' 0 "$ak"
  check 'C1 容器内 OKX secret 长度' 0 "$sk"
  check 'C1 容器内 OKX passphrase 长度' 0 "$pk"
  check 'C2 容器内 REAL_TRADING_ENABLED' False "$real_enabled"

  tok_hits=$(docker compose -f "$COMPOSE_FILE" logs api 2>/dev/null | grep -Fc "$TOK" || true)
  secret_hits=$(docker compose -f "$COMPOSE_FILE" logs api worker 2>/dev/null | grep -cE 'okx_api_secret=[^ ]+' || true)
  echo "C3 明文令牌出现在 api 日志中的次数: $tok_hits"
  echo "C4 OKX 密钥值出现在 api/worker 日志中的次数: $secret_hits"
  check 'C3 明文令牌未落日志' 0 "${tok_hits:-0}"
  check 'C4 OKX 密钥未落日志' 0 "${secret_hits:-0}"

  echo
  echo "输出已保存到 $OUT"
}

main "$@"
rc=$?

echo
if (( FAILS > 0 )); then
  echo "断言失败 ${FAILS} 项，详见上方 FAIL 行（退出码 1）"
  exit 1
fi
if (( rc != 0 )); then
  echo "脚本未跑完全部检查（退出码 $rc）"
  exit 1
fi
echo '全部断言通过（退出码 0）'
exit 0
