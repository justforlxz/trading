#!/usr/bin/env bash
# P2 阶段一键验收脚本（MKACG-700 / P2-08）。
#
# 目标链：造组合 → 收紧限额 → 触发超限 → 分级处置 → 事件落库 → 恢复限额。
#
# 约束（见 docs/architecture/api-contract.md）：
#   * 业务断言只通过 HTTP 调用 API，不 import 后端模块、不直连数据库；
#     `docker compose exec` 只用于两件事：步骤 0 读 alembic 版本，
#     步骤 1 幂等写入一条验收专用组合（P2 尚无「创建组合」的公开接口）。
#   * 所有异步任务都以轮询 `GET /ops/job-runs/{id}` 等待终态，不用固定 sleep。
#   * 每一步独立可复跑：组合以固定 strategy_key 幂等重建，评估键取当天日期，
#     因此重复执行不会叠加事件。
#
# 退出码：0 = 全部步骤通过；非 0 = 某一步失败（标准错误会打印失败步骤名）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"

API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE=${API_BASE:-$API_ROOT/api/v1}
WEB_BASE=${WEB_BASE:-http://localhost:5173}

POLL_TIMEOUT=${POLL_TIMEOUT:-600}
POLL_INTERVAL=${POLL_INTERVAL:-2}

STRATEGY_KEY=${STRATEGY_KEY:-p2-smoke-strategy}
EVALUATION_KEY=${EVALUATION_KEY:-$(date -u +%Y-%m-%d)}

ARTIFACT=${ARTIFACT:-$REPO_ROOT/docs/reports/p2-smoke-artifacts.json}

mkdir -p "$HOME/.cache"
WORK_DIR=$(mktemp -d "$HOME/.cache/p2-smoke.XXXXXX")
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

require_job_terminal() {
  local body=$1 what=$2 status
  status=$(jq -r '.status' <<<"$body")
  case $status in
    ok | partial | skipped) : ;;
    *) fail "${what} 任务失败（${status}）：${body}" ;;
  esac
  printf '%s' "$body"
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
    docker compose -f "$COMPOSE_FILE" exec -T api alembic current 2>/dev/null \
      | tr -d '\r' | sed -n '$p'
  ); then
    fail "读取 alembic current 失败（需要 docker 与运行中的 compose 栈）"
  fi
  [[ $migration == *"0007_risk_schema"* ]] || fail "迁移版本不是 0007_risk_schema：$migration"
fi
step_end "$web_code" "API health=ok；迁移=$migration"
ARTIFACT_ENTRIES+=("$(jq -n --arg m "$migration" --arg w "$web_code" '{migration:$m, web_status:$w}')")

# ---------------------------------------------------------------- 步骤 1

step_begin 1 "造组合：幂等写入验收专用组合与净值"
seed_json=$(
  docker compose -f "$COMPOSE_FILE" exec -T api \
    env "RISK_SMOKE_STRATEGY_KEY=$STRATEGY_KEY" python - <<'PY'
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.backtest.models import BacktestEquityPoint, BacktestRun
from app.db.session import session_factory
from app.market.models import Candle, Instrument
from app.research import models as _research_models
from app.risk.models import RiskEvent
from app.strategy.models import Strategy, StrategyLeg

STRATEGY_KEY = os.environ["RISK_SMOKE_STRATEGY_KEY"]
LEGS = (
    ("P2SMKA-USDT-SWAP", "long", Decimal("0.9")),
    ("P2SMKB-USDT-SWAP", "short", Decimal("0.5")),
)
CAPITAL = Decimal("100000")


async def ensure_instrument(session, inst_id: str) -> Instrument:
    existing = (
        await session.execute(select(Instrument).where(Instrument.inst_id == inst_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    base = inst_id.split("-")[0]
    instrument = Instrument(
        inst_id=inst_id,
        inst_family=base,
        uly=base,
        inst_category=1,
        asset_class="us_stock",
        exchange="OKX",
        ct_val=Decimal("1"),
        ct_val_ccy="USDT",
        lot_sz=Decimal("1"),
        min_sz=Decimal("1"),
        tick_sz=Decimal("0.01"),
        lever=Decimal("10"),
        state="live",
        rule_type="normal",
        raw={},
    )
    session.add(instrument)
    await session.flush()
    return instrument


async def main() -> None:
    async with session_factory() as session:
        for stale in (
            await session.execute(
                select(Strategy).where(Strategy.strategy_key == STRATEGY_KEY)
            )
        ).scalars():
            await session.execute(delete(RiskEvent).where(RiskEvent.strategy_id == stale.id))
            for run in (
                await session.execute(
                    select(BacktestRun).where(BacktestRun.strategy_id == stale.id)
                )
            ).scalars():
                await session.execute(
                    delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id)
                )
            await session.execute(delete(BacktestRun).where(BacktestRun.strategy_id == stale.id))
            await session.execute(delete(StrategyLeg).where(StrategyLeg.strategy_id == stale.id))
            await session.execute(delete(Strategy).where(Strategy.id == stale.id))
        await session.commit()

        now = datetime.now(UTC)
        instrument_ids: dict[str, int] = {}
        for inst_id, _side, _weight in LEGS:
            instrument = await ensure_instrument(session, inst_id)
            instrument_ids[inst_id] = instrument.id
            session.add(
                Candle(
                    instrument_id=instrument.id,
                    bar="1d",
                    open_time=now - timedelta(hours=1),
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal("100"),
                    vol=Decimal("1"),
                    vol_ccy=Decimal("1"),
                    vol_ccy_quote=Decimal("100"),
                    confirm=True,
                    source="p2-smoke",
                )
            )

        strategy = Strategy(
            strategy_key=STRATEGY_KEY,
            name="P2 验收组合",
            kind="directional",
            status="approved",
            templates=[],
            params={},
            content_hash="0" * 64,
            version=1,
        )
        session.add(strategy)
        await session.flush()

        for rank, (inst_id, side, weight) in enumerate(LEGS):
            session.add(
                StrategyLeg(
                    strategy_id=strategy.id,
                    instrument_id=instrument_ids[inst_id],
                    side=side,
                    target_weight=weight,
                    rationale="p2 smoke",
                    rank=rank,
                )
            )

        run = BacktestRun(
            run_key=f"{STRATEGY_KEY}-run",
            strategy_id=strategy.id,
            strategy_version=1,
            window_start=now - timedelta(days=30),
            window_end=now,
            bar="1d",
            initial_capital=CAPITAL,
            cost_model={},
            params={},
            status="ok",
        )
        session.add(run)
        await session.flush()

        for offset, equity in enumerate((CAPITAL, CAPITAL * Decimal("0.8"))):
            session.add(
                BacktestEquityPoint(
                    run_id=run.id,
                    ts=now - timedelta(days=2) + timedelta(hours=offset),
                    equity=equity,
                    cash=equity,
                    exposure=Decimal("0"),
                    drawdown=(CAPITAL - equity) / CAPITAL,
                )
            )

        await session.commit()
        print(
            json.dumps(
                {
                    "strategy_id": strategy.id,
                    "run_id": run.id,
                    "instrument_ids": instrument_ids,
                    "capital": str(CAPITAL),
                }
            )
        )


asyncio.run(main())
PY
)
STRATEGY_ID=$(jq -r '.strategy_id' <<<"$seed_json")
RUN_ID=$(jq -r '.run_id' <<<"$seed_json")
[[ $STRATEGY_ID =~ ^[0-9]+$ ]] || fail "造组合失败，未拿到 strategy_id：$seed_json"
step_end "n/a" "strategy_id=${STRATEGY_ID}，run_id=${RUN_ID}，2 腿（0.9 long / 0.5 short）"
ARTIFACT_ENTRIES+=("$(jq -n --argjson s "$STRATEGY_ID" --argjson r "$RUN_ID" '{seeded_strategy:$s, seeded_backtest:$r}')")

# ---------------------------------------------------------------- 步骤 2

step_begin 2 "读取限额：GET /risk/policy?strategy_id"
http GET "/risk/policy?strategy_id=$STRATEGY_ID"
expect_status 200
base_version=$(jq -r '.version' <<<"$HTTP_BODY")
[[ $base_version =~ ^[0-9]+$ ]] || fail "限额版本不是整数：$HTTP_BODY"
[[ $(jq -r '.thresholds | type' <<<"$HTTP_BODY") == "object" ]] || fail "限额快照缺少 thresholds：$HTTP_BODY"
step_end 200 "阈值版本 v${base_version}（不存在时服务端自动创建 v1）"
ARTIFACT_ENTRIES+=("$(jq -n --argjson v "$base_version" '{policy_version_initial:$v}')")

# ---------------------------------------------------------------- 步骤 3

step_begin 3 "收紧限额：PUT /risk/policy"
tight_payload=$(jq -n --argjson v "$base_version" --argjson s "$STRATEGY_ID" '{
  expected_version: $v,
  updated_by: "p2-smoke",
  note: "P2 验收：收紧阈值以触发超限",
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
}')
http PUT /risk/policy "$tight_payload"
expect_status 200
tight_version=$(jq -r '.version' <<<"$HTTP_BODY")
(( tight_version > base_version )) || fail "更新后版本未递增：${base_version} → ${tight_version}"
step_end 200 "阈值版本 ${base_version} → ${tight_version}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson v "$tight_version" '{policy_version_tight:$v}')")

# ---------------------------------------------------------------- 步骤 4

step_begin 4 "触发超限：GET /risk/status?strategy_id"
http GET "/risk/status?strategy_id=$STRATEGY_ID"
expect_status 200
[[ $(jq -r '.allowed' <<<"$HTTP_BODY") == "false" ]] || fail "收紧后仍放行：$HTTP_BODY"
breach_codes=$(jq -r '[.breaches[].code] | unique | join(",")' <<<"$HTTP_BODY")
[[ $breach_codes == *"gross_exposure_exceeded"* ]] || fail "未命中总敞口限额：$breach_codes"
[[ $breach_codes == *"concentration_exceeded"* ]] || fail "未命中集中度限额：$breach_codes"
status_reason=$(jq -r '.reason' <<<"$HTTP_BODY")
[[ $status_reason == "limit_breach" ]] || fail "拒绝原因不是 limit_breach：${status_reason}"
step_end 200 "allowed=false，reason=${status_reason}，命中：${breach_codes}"
ARTIFACT_ENTRIES+=("$(jq -n --arg r "$status_reason" --arg c "$breach_codes" '{status_reason:$r, breach_codes:$c}')")

# ---------------------------------------------------------------- 步骤 5

step_begin 5 "落库评估：POST /risk/evaluate（同参数两次）"
eval_payload=$(jq -n --argjson s "$STRATEGY_ID" --arg k "$EVALUATION_KEY" \
  '{strategy_id:$s, evaluation_key:$k}')
http POST /risk/evaluate "$eval_payload"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "评估接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
evaluate_code=$HTTP_STATUS
evaluate_run=$(jq -r '.run_id' <<<"$HTTP_BODY")
evaluate_job=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.dispatched' <<<"$HTTP_BODY") == "true" ]]; then
  require_job_terminal "$(poll_job "$evaluate_job")" "风控评估" >/dev/null
fi

http GET "/risk/events?strategy_id=${STRATEGY_ID}&kind=limit_breach&limit=100"
expect_status 200
limit_events=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( limit_events >= 1 )) || fail "未产生 limit_breach 事件"

http POST /risk/evaluate "$eval_payload"
[[ $HTTP_STATUS == 200 || $HTTP_STATUS == 202 ]] || fail "重复评估返回 HTTP $HTTP_STATUS"
[[ $(jq -r '.run_id' <<<"$HTTP_BODY") == "$evaluate_run" ]] || fail "重复评估未复用同一 run_id"
[[ $(jq -r '.created' <<<"$HTTP_BODY") == "false" ]] || fail "重复评估不应新建任务"

http GET "/risk/events?strategy_id=${STRATEGY_ID}&kind=limit_breach&limit=100"
expect_status 200
limit_events_again=$(jq -r '.items | length' <<<"$HTTP_BODY")
[[ $limit_events_again == "$limit_events" ]] || fail "重复评估新增了重复事件：${limit_events} → ${limit_events_again}"
step_end "$evaluate_code" "run_id=${evaluate_run}，limit_breach 事件 ${limit_events} 条（重复评估未叠加）"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$evaluate_run" --argjson n "$limit_events" '{evaluate_run:$r, limit_breach_events:$n}')")

# ---------------------------------------------------------------- 步骤 6

step_begin 6 "分级处置：GET /risk/events?kind=drawdown"
http GET "/risk/events?strategy_id=${STRATEGY_ID}&kind=drawdown&limit=100"
expect_status 200
drawdown_events=$(jq -r '.items | length' <<<"$HTTP_BODY")
(( drawdown_events >= 1 )) || fail "未产生 drawdown 事件"
drawdown_action=$(jq -r '[.items[] | select(.action != "none")][0].action // "none"' <<<"$HTTP_BODY")
drawdown_severity=$(jq -r '[.items[] | select(.action != "none")][0].severity // "none"' <<<"$HTTP_BODY")
[[ $drawdown_action == "reduce" ]] || fail "回撤 20% 应触发 reduce，实际 ${drawdown_action}"
[[ $drawdown_severity == "tier2" ]] || fail "回撤 20% 应为二级处置，实际 ${drawdown_severity}"
step_end 200 "drawdown 事件 ${drawdown_events} 条，处置动作=${drawdown_action}/${drawdown_severity}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson n "$drawdown_events" --arg a "$drawdown_action" --arg s "$drawdown_severity" '{drawdown_events:$n, drawdown_action:$a, drawdown_severity:$s}')")

# ---------------------------------------------------------------- 步骤 7

step_begin 7 "全局组合：GET /risk/status"
http GET /risk/status
expect_status 200
[[ $(jq -r '.scope' <<<"$HTTP_BODY") == "global" ]] || fail "全局状态 scope 不是 global：$HTTP_BODY"
[[ $(jq -r '.allowed' <<<"$HTTP_BODY") == "false" ]] || fail "全局组合在收紧阈值下仍放行"
global_breaches=$(jq -r '.breaches | length' <<<"$HTTP_BODY")
(( global_breaches >= 1 )) || fail "全局组合未命中任何限额"
step_end 200 "scope=global，allowed=false，命中 ${global_breaches} 条限额"

# ---------------------------------------------------------------- 步骤 8

step_begin 8 "恢复限额：PUT /risk/policy"
restore_payload=$(jq -n --argjson v "$tight_version" --argjson s "$STRATEGY_ID" '{
  expected_version: $v,
  updated_by: "p2-smoke",
  note: "P2 验收：恢复默认阈值",
  strategy_id: $s,
  thresholds: {
    max_order_notional: "20000",
    max_leg_weight: "0.6",
    max_leverage: "1.0",
    max_gross_exposure: "1.0",
    max_net_exposure: "1.0",
    max_instrument_weight: "0.6",
    max_concentration: "0.5",
    drawdown_warn: "0.05",
    drawdown_reduce: "0.10",
    drawdown_close: "0.20",
    funding_rate_threshold: "0.0005",
    min_depth_notional: "20000"
  }
}')
http PUT /risk/policy "$restore_payload"
expect_status 200
restored_version=$(jq -r '.version' <<<"$HTTP_BODY")
(( restored_version > tight_version )) || fail "恢复后版本未递增"
step_end 200 "阈值版本 ${tight_version} → ${restored_version}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson v "$restored_version" '{policy_version_restored:$v}')")

# ---------------------------------------------------------------- 步骤 9

step_begin 9 "输出汇总"
printf '\n%-4s %-44s %-6s %-9s %s\n' "步骤" "内容" "HTTP" "耗时(ms)" "结论"
for row in "${SUMMARY_ROWS[@]}"; do
  IFS='|' read -r n name code ms note <<<"$row"
  printf '%-4s %-44s %-6s %-9s %s\n' "$n" "$name" "$code" "$ms" "$note"
done

mkdir -p "$(dirname "$ARTIFACT")"
printf '%s\n' "${ARTIFACT_ENTRIES[@]}" | jq -s \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg api "$API_BASE" --arg key "$EVALUATION_KEY" \
  '{generated_at:$ts, api_base:$api, evaluation_key:$key, steps:.}' >"$ARTIFACT" \
  || fail "写入验收产物失败：$ARTIFACT"
printf '\n验收产物：%s\n' "${ARTIFACT#"$REPO_ROOT"/}"
step_end 200 "全链路通过，产物已写入 ${ARTIFACT#"$REPO_ROOT"/}"
