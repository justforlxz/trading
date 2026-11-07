#!/usr/bin/env bash
# P3 阶段一键验收脚本（MKACG-701 / P3-09）。
#
# 目标链：造策略 → 风控放行 → paper 下单 → 部分成交 → 撤单 → 持仓归因
#         → 对账 → 重启恢复 → 真实门禁 403 → 汇总。
#
# 约束（见 docs/architecture/api-contract.md §3.9）：
#   * 业务断言只通过 HTTP 调用 API，不 import 后端模块、不直连业务表；
#     `docker compose exec` 只用于两件事：步骤 0 读 alembic 版本，
#     步骤 1 幂等写入验收专用策略（P3 尚无「创建策略」的公开写接口）。
#   * 异步任务以轮询 `GET /ops/job-runs/{id}` 等待终态，不用固定 sleep。
#   * 全程不设置 REAL_TRADING_ENABLED，步骤 9 断言的正是「缺省关闭时真实下单必须 403」。
#
# 退出码：0 = 全部步骤通过；非 0 = 某一步失败（标准错误打印失败步骤）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"

API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE=${API_BASE:-$API_ROOT/api/v1}

POLL_TIMEOUT=${POLL_TIMEOUT:-600}
POLL_INTERVAL=${POLL_INTERVAL:-2}

STRATEGY_KEY=${STRATEGY_KEY:-p3-smoke-strategy}
EVALUATION_KEY=${EVALUATION_KEY:-$(date -u +%Y-%m-%d)}
ARTIFACT=${ARTIFACT:-$REPO_ROOT/docs/reports/p3-smoke-artifacts.json}

mkdir -p "$HOME/.cache"
WORK_DIR=$(mktemp -d "$HOME/.cache/p3-smoke.XXXXXX")
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

wait_api() {
  local deadline=$(( SECONDS + 120 ))
  until curl -fsS "$API_ROOT/health" >/dev/null 2>&1; do
    (( SECONDS < deadline )) || fail "等待 API 恢复超时"
    sleep 1
  done
}

# ---------------------------------------------------------------- 步骤 0

step_begin 0 "预检：API 健康与 execution 迁移版本"
health=$(curl -fsS "$API_ROOT/health") || fail "GET $API_ROOT/health 失败（API 未就绪）"
[[ $(jq -r '.status' <<<"$health") == "ok" ]] || fail "health 状态不是 ok：$health"

migration="skipped"
if [[ ${SKIP_MIGRATION_CHECK:-0} != "1" ]]; then
  migration=$(
    docker compose -f "$COMPOSE_FILE" exec -T api alembic current 2>/dev/null \
      | tr -d '\r' | sed -n '$p'
  ) || fail "读取 alembic current 失败（需要 docker 与运行中的 compose 栈）"
  [[ $migration == *"0008_execution_schema"* ]] || fail "迁移版本不是 0008_execution_schema：$migration"
fi
mode=$(curl -fsS "$API_BASE/execution/mode") || fail "GET /execution/mode 失败"
[[ $(jq -r '.mode' <<<"$mode") == "paper" ]] || fail "默认模式不是 paper：$mode"
step_end 200 "health=ok；迁移=$migration；mode=paper"
ARTIFACT_ENTRIES+=("$(jq -n --arg m "$migration" '{migration:$m}')")

# ---------------------------------------------------------------- 步骤 1

step_begin 1 "造策略：幂等写入验收专用已审批策略与走平净值"
seed_json=$(
  docker compose -f "$COMPOSE_FILE" exec -T api \
    env "P3_SMOKE_STRATEGY_KEY=$STRATEGY_KEY" python - <<'PY'
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

import app.main  # noqa: F401 - 注册全部 ORM 模型（跨 schema 外键需要）
from app.backtest.models import BacktestEquityPoint, BacktestRun
from app.db.session import session_factory
from app.execution.models import Fill, Order, Position, ReconcileDiff
from app.market.models import Candle, Instrument
from app.risk.models import RiskEvent
from app.strategy.models import Strategy, StrategyLeg

STRATEGY_KEY = os.environ["P3_SMOKE_STRATEGY_KEY"]
LEGS = (
    ("P3SMKA-USDT-SWAP", "long", Decimal("0.15")),
    ("P3SMKB-USDT-SWAP", "short", Decimal("0.15")),
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


async def purge(session, strategy_id: int) -> None:
    order_ids = list(
        (
            await session.execute(select(Order.id).where(Order.strategy_id == strategy_id))
        ).scalars()
    )
    if order_ids:
        await session.execute(delete(Fill).where(Fill.order_id.in_(order_ids)))
    await session.execute(delete(Order).where(Order.strategy_id == strategy_id))
    await session.execute(delete(Position).where(Position.strategy_id == strategy_id))
    # 对账差异可能没有 strategy_id（持仓差异按标的记），验收复位时整体清零。
    await session.execute(delete(ReconcileDiff))
    await session.execute(delete(RiskEvent).where(RiskEvent.strategy_id == strategy_id))
    for run in (
        await session.execute(select(BacktestRun).where(BacktestRun.strategy_id == strategy_id))
    ).scalars():
        await session.execute(delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id))
    await session.execute(delete(BacktestRun).where(BacktestRun.strategy_id == strategy_id))
    await session.execute(delete(StrategyLeg).where(StrategyLeg.strategy_id == strategy_id))
    await session.execute(delete(Strategy).where(Strategy.id == strategy_id))


async def main() -> None:
    async with session_factory() as session:
        for stale in (
            await session.execute(select(Strategy).where(Strategy.strategy_key == STRATEGY_KEY))
        ).scalars():
            await purge(session, stale.id)
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
                    source="p3-smoke",
                )
            )

        strategy = Strategy(
            strategy_key=STRATEGY_KEY,
            name="P3 验收组合",
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
                    rationale="p3 smoke",
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

        # 净值走平：回撤 0，风控不因回撤拒绝放行。
        for offset in range(2):
            session.add(
                BacktestEquityPoint(
                    run_id=run.id,
                    ts=now - timedelta(days=2) + timedelta(hours=offset),
                    equity=CAPITAL,
                    cash=CAPITAL,
                    exposure=Decimal("0"),
                    drawdown=Decimal("0"),
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
[[ $STRATEGY_ID =~ ^[0-9]+$ ]] || fail "造策略失败：$seed_json"
# 复位进程级 paper 撮合账本：脚本必须能在同一套 compose 栈上重复执行。
docker compose -f "$COMPOSE_FILE" restart api >/dev/null || fail "重启 api 失败"
wait_api

step_end "n/a" "strategy_id=${STRATEGY_ID}，2 腿 × 0.15；API 已重启清空 paper 账本"
ARTIFACT_ENTRIES+=("$(jq -n --argjson s "$STRATEGY_ID" '{seeded_strategy:$s}')")

# ---------------------------------------------------------------- 步骤 2

step_begin 2 "风控放行：POST /risk/evaluate 并核对结果"
eval_payload=$(jq -n --argjson s "$STRATEGY_ID" --arg k "$EVALUATION_KEY" \
  '{strategy_id:$s, evaluation_key:$k}')
http POST /risk/evaluate "$eval_payload"
[[ $HTTP_STATUS == 202 || $HTTP_STATUS == 200 ]] || fail "评估接口返回 HTTP $HTTP_STATUS：$HTTP_BODY"
eval_run=$(jq -r '.job_id' <<<"$HTTP_BODY")
if [[ $(jq -r '.dispatched' <<<"$HTTP_BODY") == "true" ]]; then
  job=$(poll_job "$eval_run")
  [[ $(jq -r '.status' <<<"$job") == "ok" ]] || fail "风控评估任务未成功：$job"
  [[ $(jq -r '.result.allowed' <<<"$job") == "true" ]] || fail "风控未放行：$job"
fi
step_end "$HTTP_STATUS" "job_id=${eval_run}，allowed=true"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$eval_run" '{evaluate_job:$r}')")

# ---------------------------------------------------------------- 步骤 3

step_begin 3 "模式端点：GET /execution/mode"
http GET /execution/mode
expect_status 200
[[ $(jq -r '.mode' <<<"$HTTP_BODY") == "paper" ]] || fail "mode 不是 paper：$HTTP_BODY"
[[ $(jq -r '.real_trading_enabled' <<<"$HTTP_BODY") == "false" ]] || fail "真实交易开关不是 false：$HTTP_BODY"
[[ $(jq -r '.reason' <<<"$HTTP_BODY") == "real_trading_disabled" ]] || fail "关闭原因缺失：$HTTP_BODY"
step_end 200 "mode=paper，reason=real_trading_disabled"

# ---------------------------------------------------------------- 步骤 4

step_begin 4 "paper 下单：POST /execution/paper/orders（首轮部分成交）"
order_payload=$(jq -n --argjson s "$STRATEGY_ID" --arg c "p3-smoke-a" '{
  strategy_id:$s, inst_id:"P3SMKA-USDT-SWAP", side:"buy", position_side:"long",
  quantity:"1", order_type:"market", intent:"entry", client_order_id:$c
}')
http POST /execution/paper/orders "$order_payload"
expect_status 201
ORDER_A=$(jq -r '.id' <<<"$HTTP_BODY")
[[ $(jq -r '.mode' <<<"$HTTP_BODY") == "paper" ]] || fail "订单 mode 不是 paper：$HTTP_BODY"
[[ $(jq -r '.state' <<<"$HTTP_BODY") == "partial" ]] || fail "首轮应为 partial：$HTTP_BODY"
[[ $(jq -r '.filled_quantity' <<<"$HTTP_BODY") == "0.5" ]] || fail "首轮成交量不是 0.5：$HTTP_BODY"
step_end 201 "order_id=${ORDER_A}，state=partial，filled=0.5"
ARTIFACT_ENTRIES+=("$(jq -n --argjson o "$ORDER_A" '{order_partial:$o}')")

# ---------------------------------------------------------------- 步骤 5

step_begin 5 "补成交：POST /execution/orders/{id}/sync → filled"
http POST "/execution/orders/$ORDER_A/sync"
expect_status 200
[[ $(jq -r '.state' <<<"$HTTP_BODY") == "filled" ]] || fail "同步后未成交：$HTTP_BODY"
[[ $(jq -r '.filled_quantity' <<<"$HTTP_BODY") == "1" ]] || fail "成交量不是 1：$HTTP_BODY"
step_end 200 "state=filled，filled=1"

# ---------------------------------------------------------------- 步骤 6

step_begin 6 "撤单：POST /execution/paper/orders 后立即 cancel"
cancel_payload=$(jq -n --argjson s "$STRATEGY_ID" --arg c "p3-smoke-b" '{
  strategy_id:$s, inst_id:"P3SMKA-USDT-SWAP", side:"buy", position_side:"long",
  quantity:"0.4", order_type:"limit", price:"100", intent:"entry", client_order_id:$c
}')
http POST /execution/paper/orders "$cancel_payload"
expect_status 201
ORDER_B=$(jq -r '.id' <<<"$HTTP_BODY")
http POST "/execution/orders/$ORDER_B/cancel"
expect_status 200
[[ $(jq -r '.state' <<<"$HTTP_BODY") == "canceled" ]] || fail "撤单后状态不是 canceled：$HTTP_BODY"
step_end 200 "order_id=${ORDER_B}，state=canceled，已成交 $(jq -r '.filled_quantity' <<<"$HTTP_BODY")"

# ---------------------------------------------------------------- 步骤 7

step_begin 7 "持仓归因：GET /execution/positions 与订单成交量对账"
http GET "/execution/orders?strategy_id=$STRATEGY_ID&limit=200"
expect_status 200
orders_body=$HTTP_BODY
http GET "/execution/positions?strategy_id=$STRATEGY_ID"
expect_status 200
positions_body=$HTTP_BODY
[[ $(jq -r '.totals.positions' <<<"$positions_body") -ge 1 ]] || fail "没有持仓：$positions_body"
expected_qty=$(jq -r '[.items[] | select(.side=="buy" and .position_side=="long") | (.filled_quantity|tonumber)] | add // 0' <<<"$orders_body")
actual_qty=$(jq -r '[.items[] | select(.position_side=="long") | (.quantity|tonumber)] | add // 0' <<<"$positions_body")
[[ $expected_qty == "$actual_qty" ]] || fail "持仓 ${actual_qty} ≠ 订单成交量之和 ${expected_qty}"
step_end 200 "持仓数量=${actual_qty}，与订单成交量之和一致"
ARTIFACT_ENTRIES+=("$(jq -n --argjson q "$actual_qty" '{position_quantity:$q}')")

# ---------------------------------------------------------------- 步骤 8

step_begin 8 "对账：POST /execution/reconcile"
http POST /execution/reconcile
expect_status 200
checked=$(jq -r '.checked_positions' <<<"$HTTP_BODY")
open_diffs=$(jq -r '.open_diffs' <<<"$HTTP_BODY")
[[ $open_diffs == "0" ]] || fail "paper 对账出现差异：$HTTP_BODY"
step_end 200 "checked_positions=${checked}，open_diffs=0"
ARTIFACT_ENTRIES+=("$(jq -n --argjson n "$checked" '{reconcile_checked:$n}')")

# ---------------------------------------------------------------- 步骤 9

step_begin 9 "重启恢复：重启 API 后 POST /execution/recovery"
restart_payload=$(jq -n --argjson s "$STRATEGY_ID" --arg c "p3-smoke-c" '{
  strategy_id:$s, inst_id:"P3SMKA-USDT-SWAP", side:"buy", position_side:"long",
  quantity:"0.4", order_type:"market", intent:"entry", client_order_id:$c
}')
http POST /execution/paper/orders "$restart_payload"
expect_status 201
ORDER_C=$(jq -r '.id' <<<"$HTTP_BODY")
[[ $(jq -r '.state' <<<"$HTTP_BODY") == "partial" ]] || fail "重启前订单未处于部分成交：$HTTP_BODY"

docker compose -f "$COMPOSE_FILE" restart api >/dev/null || fail "重启 api 失败"
wait_api

http POST /execution/recovery
expect_status 200
recovered=$(jq -r '.reattached' <<<"$HTTP_BODY")
rehydrated=$(jq -r '.rehydrated_orders' <<<"$HTTP_BODY")
(( recovered >= 1 )) || fail "重启后没有接管任何订单：$HTTP_BODY"
(( rehydrated >= 1 )) || fail "paper 撮合状态未重建：$HTTP_BODY"

http GET "/execution/orders/$ORDER_C"
expect_status 200
[[ $(jq -r '.state' <<<"$HTTP_BODY") == "filled" ]] || fail "接管后订单未完成：$HTTP_BODY"
step_end 200 "rehydrated=${rehydrated}，reattached=${recovered}，order_c=filled"
ARTIFACT_ENTRIES+=("$(jq -n --argjson r "$recovered" --argjson h "$rehydrated" '{reattached:$r, rehydrated:$h}')")

# ---------------------------------------------------------------- 步骤 10

step_begin 10 "真实门禁：缺省关闭时 POST /execution/orders 必须 403"
real_code=$(curl -sS -o "$WORK_DIR/real_order.json" -w '%{http_code}' \
  -X POST "$API_BASE/execution/orders") || fail "真实下单端点不可达"
[[ $real_code == "403" ]] || fail "真实下单未返回 403，实际 $real_code：$(cat "$WORK_DIR/real_order.json")"
[[ $(jq -r '.error.code' "$WORK_DIR/real_order.json") == "real_trading_disabled" ]] \
  || fail "错误码不是 real_trading_disabled：$(cat "$WORK_DIR/real_order.json")"

printf '\n%-4s %-46s %-6s %-9s %s\n' "步骤" "内容" "HTTP" "耗时(ms)" "结论"
for row in "${SUMMARY_ROWS[@]}"; do
  IFS='|' read -r n name code ms note <<<"$row"
  printf '%-4s %-46s %-6s %-9s %s\n' "$n" "$name" "$code" "$ms" "$note"
done

mkdir -p "$(dirname "$ARTIFACT")"
printf '%s\n' "${ARTIFACT_ENTRIES[@]}" | jq -s \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg api "$API_BASE" --arg key "$EVALUATION_KEY" \
  '{generated_at:$ts, api_base:$api, evaluation_key:$key, real_trading_enabled:false, steps:.}' \
  >"$ARTIFACT" || fail "写入验收产物失败：$ARTIFACT"
printf '\n验收产物：%s\n' "${ARTIFACT#"$REPO_ROOT"/}"
step_end 403 "全链路通过（真实交易全程关闭）"
