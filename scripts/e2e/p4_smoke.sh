#!/usr/bin/env bash
# P4 阶段一键验收脚本（MKACG-702 / P4-07）。
#
# 目标链：确认只读边界 → 幂等播种验收数据 → 解释市场 → 解释关系 → 解释策略
#         → 解读回测 → 只读问答语料（answered/unlicensed）→ 写意图语料（forbidden）
#         → 审计已记录。
#
# 语料：`backend/tests/ai/data/query_cases.json` 是测试与冒烟的**单一事实源**，步骤 6/7 用
# python 解析后逐条按「允许结果集合」断言，不在脚本里另维护问答清单。
#
# 约束（见 docs/architecture/api-contract.md §3.10）：
#   * 业务断言只通过 HTTP 调用 API；`docker compose exec` 仅用于三件事：
#     读 alembic 版本、幂等播种验收数据、查询 ops.audit_log 验证审计。
#   * AI 默认关闭：脚本在规则式 provider（AI_PROVIDER=rule_based）下运行，不访问任何外部模型。
#     若当前栈未开启，脚本会用环境变量重建 api 容器为规则式模式。
#   * 全程不设置 REAL_TRADING_ENABLED；写意图只验证「被拒绝且没有产生订单」。
#
# 退出码：0 = 全部步骤通过；非 0 = 某一步失败（标准错误打印失败步骤）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"

API_ROOT=${API_ROOT:-http://localhost:8000}
API_BASE=${API_BASE:-$API_ROOT/api/v1}
ARTIFACT=${ARTIFACT:-$REPO_ROOT/docs/reports/p4-smoke-artifacts.json}

RUN_TAG=$(date -u +%Y%m%dT%H%M%S)-$$
STRATEGY_KEY=${STRATEGY_KEY:-p4-smoke-strategy}
TARGET_SYMBOL=${TARGET_SYMBOL:-P4SMK}

mkdir -p "$HOME/.cache"
WORK_DIR=$(mktemp -d "$HOME/.cache/p4-smoke.XXXXXX")
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
  local method=$1 path=$2 data=${3-} rid=${4-} out
  local -a args=(-sS -X "$method" "$API_BASE$path")
  if [[ -n $rid ]]; then args+=(-H "X-Request-ID: $rid"); fi
  if [[ -n $data ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "$data")
  fi
  out=$(curl "${args[@]}" -w $'\n%{http_code}') \
    || fail "请求失败：$method $API_BASE$path"
  HTTP_STATUS=${out##*$'\n'}
  HTTP_BODY=${out%$'\n'*}
  return 0
}

expect_status() {
  local expected=$1
  [[ $HTTP_STATUS == "$expected" ]] || fail "期望 HTTP $expected，实际 $HTTP_STATUS；响应：$HTTP_BODY"
}

api_health() {
  curl -fsS "$API_ROOT/health" >/dev/null 2>&1
}

wait_api() {
  local deadline=$(( SECONDS + 120 ))
  until api_health; do
    (( SECONDS < deadline )) || fail "等待 API 恢复超时"
    sleep 1
  done
}

# 规则式 provider 不触网；AI 默认关闭时把当前栈切成规则式模式。
enable_ai() {
  AI_ENABLED=true AI_PROVIDER=rule_based \
    docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate api >/dev/null 2>&1 \
    || fail "重建 api 容器失败（需要 docker 与运行中的 compose 栈）"
  wait_api
}

# ---------------------------------------------------------------- 步骤 0

step_begin 0 "预检：健康、迁移版本、真实交易关闭、AI 规则式可用"
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

http GET /execution/mode
expect_status 200
[[ $(jq -r '.mode' <<<"$HTTP_BODY") == "paper" ]] || fail "默认模式不是 paper：$HTTP_BODY"
[[ $(jq -r '.real_trading_enabled' <<<"$HTTP_BODY") == "false" ]] || fail "真实交易开关不是 false：$HTTP_BODY"

http POST /ai/explain/market '{}'
if [[ $HTTP_STATUS == "503" ]]; then
  printf '  · AI 当前关闭，切换为规则式 provider（不访问外部模型）\n'
  enable_ai
  http POST /ai/explain/market '{}'
fi
expect_status 200
[[ $(jq -r '.model.provider' <<<"$HTTP_BODY") == "rule_based" ]] \
  || fail "AI provider 不是 rule_based（本脚本不访问外部模型）：$HTTP_BODY"
[[ $(jq -r '.degraded' <<<"$HTTP_BODY") == "true" ]] || fail "规则式回答未标记 degraded=true：$HTTP_BODY"
step_end 200 "health=ok；迁移=$migration；mode=paper；provider=rule_based"
ARTIFACT_ENTRIES+=("$(jq -n --arg m "$migration" '{migration:$m, provider:"rule_based"}')")

# ---------------------------------------------------------------- 步骤 1

step_begin 1 "幂等播种：验收目标、关系快照、已审批策略、回测指标"
seed_json=$(
  docker compose -f "$COMPOSE_FILE" exec -T api \
    env "P4_SMOKE_STRATEGY_KEY=$STRATEGY_KEY" "P4_SMOKE_TARGET_SYMBOL=$TARGET_SYMBOL" \
    python - <<'PY'
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

import app.main  # noqa: F401 - 注册全部 ORM 模型（跨 schema 外键需要）
from app.backtest.models import BacktestEquityPoint, BacktestMetric, BacktestRun
from app.db.session import session_factory
from app.market.core.candles import expected_open_times
from app.market.models import Candle, Instrument
from app.research.models import RelationEdge, RelationSnapshot, TargetSymbol
from app.strategy.models import Strategy, StrategyApproval, StrategyLeg

STRATEGY_KEY = os.environ["P4_SMOKE_STRATEGY_KEY"]
TARGET_SYMBOL = os.environ["P4_SMOKE_TARGET_SYMBOL"]
LEGS = (
    ("P4SMKA-USDT-SWAP", "long", Decimal("0.20")),
    ("P4SMKB-USDT-SWAP", "short", Decimal("0.20")),
)
CAPITAL = Decimal("100000")
METRICS = {
    "annualized_return": ("-0.4022330000", "ratio"),
    "cost_ratio": ("0.0012100000", "ratio"),
    "max_drawdown": ("0.3812000000", "ratio"),
    "profit_loss_ratio": ("0.8123000000", "ratio"),
    "sharpe": ("-1.8181257148", "ratio"),
    "sortino": ("-2.1133000000", "ratio"),
    "total_return": ("-0.3236520556", "ratio"),
    "trade_count": ("24.0000000000", "count"),
    "turnover": ("1.4321000000", "ratio"),
    "win_rate": ("0.3750000000", "ratio"),
}


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


async def purge(session, *, strategy_key: str, symbol: str) -> None:
    for strategy in (
        await session.execute(select(Strategy).where(Strategy.strategy_key == strategy_key))
    ).scalars():
        run_ids = list(
            (
                await session.execute(
                    select(BacktestRun.id).where(BacktestRun.strategy_id == strategy.id)
                )
            ).scalars()
        )
        if run_ids:
            await session.execute(delete(BacktestMetric).where(BacktestMetric.run_id.in_(run_ids)))
            await session.execute(
                delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id.in_(run_ids))
            )
            await session.execute(delete(BacktestRun).where(BacktestRun.id.in_(run_ids)))
        await session.execute(
            delete(StrategyApproval).where(StrategyApproval.strategy_id == strategy.id)
        )
        await session.execute(delete(StrategyLeg).where(StrategyLeg.strategy_id == strategy.id))
        await session.execute(delete(Strategy).where(Strategy.id == strategy.id))

    for target in (
        await session.execute(
            select(TargetSymbol).where(TargetSymbol.symbol == symbol)
        )
    ).scalars():
        snapshot_ids = list(
            (
                await session.execute(
                    select(RelationSnapshot.id).where(
                        RelationSnapshot.target_id == target.id
                    )
                )
            ).scalars()
        )
        if snapshot_ids:
            await session.execute(
                delete(RelationEdge).where(RelationEdge.snapshot_id.in_(snapshot_ids))
            )
            await session.execute(
                delete(RelationSnapshot).where(RelationSnapshot.id.in_(snapshot_ids))
            )
        await session.execute(delete(TargetSymbol).where(TargetSymbol.id == target.id))


async def main() -> None:
    async with session_factory() as session:
        await purge(session, strategy_key=STRATEGY_KEY, symbol=TARGET_SYMBOL)
        await session.commit()

        now = datetime.now(UTC)
        instruments: dict[str, Instrument] = {}
        for inst_id, _side, _weight in LEGS:
            instruments[inst_id] = await ensure_instrument(session, inst_id)
        instrument_ids = [row.id for row in instruments.values()]
        await session.execute(delete(Candle).where(Candle.instrument_id.in_(instrument_ids)))
        # 覆盖窗口与 /ai/explain/market 的口径一致：1d 桶按 UTC+8 零点对齐。
        open_times = expected_open_times(
            now - timedelta(days=30), now, "1d"
        )
        for instrument in instruments.values():
            for open_time in open_times:
                session.add(
                    Candle(
                        instrument_id=instrument.id,
                        bar="1d",
                        open_time=open_time,
                        open=Decimal("100"),
                        high=Decimal("101"),
                        low=Decimal("99"),
                        close=Decimal("100"),
                        vol=Decimal("1"),
                        vol_ccy=Decimal("1"),
                        vol_ccy_quote=Decimal("100"),
                        confirm=True,
                        source="p4-smoke",
                    )
                )

        target = TargetSymbol(
            symbol=TARGET_SYMBOL,
            exchange="NASDAQ",
            display_name="P4 验收目标",
            instrument_id=instruments["P4SMKA-USDT-SWAP"].id,
            enabled=True,
            note="p4 smoke",
        )
        session.add(target)
        await session.flush()

        snapshot = RelationSnapshot(
            target_id=target.id,
            as_of=now,
            window_bars=200,
            method="pearson",
            price_basis="close",
            lag_max=3,
            sample_size=180,
            run_key=f"{STRATEGY_KEY}-relations",
            params={},
        )
        session.add(snapshot)
        await session.flush()
        session.add(
            RelationEdge(
                snapshot_id=snapshot.id,
                counterparty_id=instruments["P4SMKB-USDT-SWAP"].id,
                coefficient=Decimal("-0.8123456789"),
                best_lag=1,
                p_value=Decimal("0.0100000000"),
                stability=Decimal("0.9000000000"),
                rank=0,
            )
        )

        strategy = Strategy(
            strategy_key=STRATEGY_KEY,
            name="P4 验收组合",
            kind="relative_value",
            status="approved",
            target_id=target.id,
            templates=["correlation", "relative_strength"],
            params={"source": "p4-smoke"},
            content_hash="0" * 64,
            version=1,
            approved_at=now,
        )
        session.add(strategy)
        await session.flush()
        for rank, (inst_id, side, weight) in enumerate(LEGS):
            session.add(
                StrategyLeg(
                    strategy_id=strategy.id,
                    instrument_id=instruments[inst_id].id,
                    side=side,
                    target_weight=weight,
                    rationale="p4 smoke",
                    rank=rank,
                )
            )
        session.add(
            StrategyApproval(
                strategy_id=strategy.id,
                decision="approved",
                content_hash="0" * 64,
                reviewer="p4-smoke",
                note="acceptance",
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
        for name, (value, unit) in METRICS.items():
            session.add(
                BacktestMetric(run_id=run.id, name=name, value=Decimal(value), unit=unit)
            )
        for offset in range(2):
            session.add(
                BacktestEquityPoint(
                    run_id=run.id,
                    ts=now - timedelta(days=2) + timedelta(hours=offset),
                    equity=CAPITAL * Decimal("0.9"),
                    cash=CAPITAL * Decimal("0.9"),
                    exposure=Decimal("0"),
                    drawdown=Decimal("0.1"),
                )
            )

        await session.commit()
        print(
            json.dumps(
                {
                    "target_id": target.id,
                    "strategy_id": strategy.id,
                    "run_id": run.id,
                    "snapshot_id": snapshot.id,
                    "inst_a": instruments["P4SMKA-USDT-SWAP"].id,
                }
            )
        )


asyncio.run(main())
PY
)
TARGET_ID=$(jq -r '.target_id' <<<"$seed_json")
STRATEGY_ID=$(jq -r '.strategy_id' <<<"$seed_json")
RUN_ID=$(jq -r '.run_id' <<<"$seed_json")
[[ $TARGET_ID =~ ^[0-9]+$ && $STRATEGY_ID =~ ^[0-9]+$ && $RUN_ID =~ ^[0-9]+$ ]] \
  || fail "播种失败：$seed_json"
step_end "n/a" "target_id=${TARGET_ID}，strategy_id=${STRATEGY_ID}，run_id=${RUN_ID}"
ARTIFACT_ENTRIES+=("$(jq -n --argjson t "$TARGET_ID" --argjson s "$STRATEGY_ID" --argjson r "$RUN_ID" \
  '{seeded_target:$t, seeded_strategy:$s, seeded_run:$r}')")

# ---------------------------------------------------------------- 步骤 2

step_begin 2 "解释市场：POST /ai/explain/market 与覆盖接口逐项一致"
RID_MARKET="p4-smoke-$RUN_TAG-market"
http POST /ai/explain/market '{}' "$RID_MARKET"
expect_status 200
market_body=$HTTP_BODY
[[ $(jq -r '.summary' <<<"$market_body") == *"数据不足"* ]] \
  || [[ -n $(jq -r '.summary' <<<"$market_body") ]] || fail "market 解释为空：$market_body"
coverage_citation=$(jq -c '[.citations[] | select(.type=="market_coverage" and .instrument_id=="P4SMKA-USDT-SWAP")][0]' <<<"$market_body")
[[ $(jq -r '.instrument_id' <<<"$coverage_citation") == "P4SMKA-USDT-SWAP" ]] \
  || fail "缺失 P4SMKA 的覆盖引用：$market_body"
http GET "/market/coverage?inst_id=P4SMKA-USDT-SWAP&bar=1d"
expect_status 200
coverage_body=$HTTP_BODY
for field in expected actual missing ratio; do
  [[ $(jq -r ".$field" <<<"$coverage_citation") == \
     $(jq -r ".summary.$field" <<<"$coverage_body") ]] \
    || fail "覆盖引用 $field 与 GET /market/coverage 不一致：citation=$(jq -r ".$field" <<<"$coverage_citation")"
done
# 同一 request id 重放：响应仍成功，但审计只留一条。
http POST /ai/explain/market '{}' "$RID_MARKET"
expect_status 200
step_end 200 "coverage 引用与 GET /market/coverage 一致；同 request_id 已重放"
ARTIFACT_ENTRIES+=("$(jq -n --argjson c "$coverage_citation" '{market_coverage:$c}')")

# ---------------------------------------------------------------- 步骤 3

step_begin 3 "解释关系：citations 与 GET /targets/{id}/relations 一致"
RID_RELATIONS="p4-smoke-$RUN_TAG-relations"
http POST /ai/explain/relations "{\"target_id\": $TARGET_ID}" "$RID_RELATIONS"
expect_status 200
relations_body=$HTTP_BODY
http GET "/targets/$TARGET_ID/relations"
expect_status 200
relations_api=$HTTP_BODY
snapshot_citation=$(jq -c '[.citations[] | select(.type=="relation_snapshot")][0]' <<<"$relations_body")
[[ $(jq -r '.snapshot_id' <<<"$snapshot_citation") == "$(jq -r '.snapshot.id' <<<"$relations_api")" ]] \
  || fail "snapshot_id 不一致：$relations_body"
[[ $(jq -r '.citations[] | select(.type=="relation_edge") | [.instrument_id, .coefficient, .best_lag] | @tsv' <<<"$relations_body") == \
   $(jq -r '.edges[] | [.counterparty_inst_id, .coefficient, .best_lag] | @tsv' <<<"$relations_api") ]] \
  || fail "关系边引用与 GET /targets/{id}/relations 不一致：$relations_body"
step_end 200 "snapshot 与边系数/最优滞后一致"
ARTIFACT_ENTRIES+=("$(jq -n --argjson s "$snapshot_citation" '{relation_snapshot:$s}')")

# ---------------------------------------------------------------- 步骤 4

step_begin 4 "解释策略：legs 与 GET /strategies/{id} 一致"
RID_STRATEGY="p4-smoke-$RUN_TAG-strategy"
http POST /ai/explain/strategy "{\"strategy_id\": $STRATEGY_ID}" "$RID_STRATEGY"
expect_status 200
strategy_body=$HTTP_BODY
http GET "/strategies/$STRATEGY_ID"
expect_status 200
strategy_api=$HTTP_BODY
[[ $(jq -r '.citations[] | select(.type=="strategy_leg") | [.inst_id, .side, .target_weight] | @tsv' <<<"$strategy_body") == \
   $(jq -r '.legs[] | [.inst_id, .side, .weight] | @tsv' <<<"$strategy_api") ]] \
  || fail "策略 leg 引用与 GET /strategies/{id} 不一致：$strategy_body"
step_end 200 "策略 $(jq -r '.legs | length' <<<"$strategy_api") 条腿逐项一致"

# ---------------------------------------------------------------- 步骤 5

step_begin 5 "解读回测：10 项指标与 GET /backtests/{id}/metrics 逐项一致"
RID_BACKTEST="p4-smoke-$RUN_TAG-backtest"
http POST /ai/explain/backtest "{\"run_id\": $RUN_ID}" "$RID_BACKTEST"
expect_status 200
backtest_body=$HTTP_BODY
http GET "/backtests/$RUN_ID/metrics"
expect_status 200
metrics_body=$HTTP_BODY
ai_metrics=$(jq -c '[.citations[] | select(.type=="backtest_metric") | {name, value}] | sort_by(.name)' <<<"$backtest_body")
api_metrics=$(jq -c '[.items[] | {name, value}] | sort_by(.name)' <<<"$metrics_body")
[[ $ai_metrics == "$api_metrics" ]] || fail "回测指标引用与 GET /backtests/{id}/metrics 不一致：$ai_metrics"
[[ $(jq -r 'length' <<<"$ai_metrics") == "10" ]] || fail "回测指标不是 10 项：$ai_metrics"
if jq -e '[.citations[] | select(.type=="backtest_metric" and .name=="total_return") | .value | startswith("-")] | any' \
  <<<"$backtest_body" >/dev/null; then
  if jq -r '.summary' <<<"$backtest_body" | grep -Eq '加仓|扩大仓位|加大仓位|增加仓位|提高仓位'; then
    fail "亏损回测出现加仓类建议：$backtest_body"
  fi
fi
step_end 200 "10 项指标逐项一致；亏损回测无加仓建议"
ARTIFACT_ENTRIES+=("$(jq -n --argjson m "$ai_metrics" '{backtest_metrics:$m}')")

# ---------------------------------------------------------------- 步骤 6

step_begin 6 "只读问答语料：POST /ai/query（answered / unlicensed 按允许集合断言）"
CASES_FILE="$REPO_ROOT/backend/tests/ai/data/query_cases.json"
[[ -f $CASES_FILE ]] || fail "缺少语料文件：$CASES_FILE"
# 语料是测试与冒烟的单一事实源: 这里只做解析, 断言仍在下面逐条执行。
python3 - "$CASES_FILE" "$WORK_DIR" <<'PY' || fail "解析 query_cases.json 失败"
import json
import os
import sys

source, out_dir = sys.argv[1], sys.argv[2]
with open(source, encoding="utf-8") as handle:
    cases = json.load(handle)["cases"]

read_rows, write_rows = [], []
for index, case in enumerate(cases):
    expect = case["expect"]
    row = "\t".join(
        [
            str(index),
            ",".join(expect),
            case.get("intent") or "-",
            json.dumps({"question": case["text"]}),
        ]
    )
    target = read_rows if ("answered" in expect or "unlicensed" in expect) else write_rows
    target.append(row)

# 空 intent 写 "-" 占位: bash 的 IFS 会合并连续制表符, 不能靠空字段占位。
for name, rows in (("cases_read.tsv", read_rows), ("cases_write.tsv", write_rows)):
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + ("\n" if rows else ""))
PY
READ_CASES="$WORK_DIR/cases_read.tsv"
WRITE_CASES="$WORK_DIR/cases_write.tsv"
[[ -s $READ_CASES && -s $WRITE_CASES ]] || fail "语料缺少 answered/unlicensed 或 forbidden 用例"

RID_QUERY=""
ANSWERED=0
while IFS=$'\t' read -r index expect intent body; do
  [[ -n $index ]] || continue
  [[ $intent == "-" ]] && intent=""
  rid="p4-smoke-$RUN_TAG-q$index"
  http POST /ai/query "$body" "$rid"
  if [[ $HTTP_STATUS == "403" ]]; then
    [[ $expect == *forbidden* ]] || fail "语料 #$index 期望 $expect，却返回 403：$HTTP_BODY"
    [[ $(jq -r '.error.code' <<<"$HTTP_BODY") == "ai_write_forbidden" ]] \
      || fail "语料 #$index 403 但错误码不是 ai_write_forbidden：$HTTP_BODY"
    continue
  fi
  expect_status 200
  [[ $(jq -r '.read_only' <<<"$HTTP_BODY") == "true" ]] || fail "语料 #$index 缺 read_only：$HTTP_BODY"
  if [[ $(jq -r '.answerable' <<<"$HTTP_BODY") == "true" ]]; then
    [[ $expect == *answered* ]] || fail "语料 #$index ($(jq -r '.question' <<<"$body")) 期望 $expect，却作答：$HTTP_BODY"
    [[ -n $(jq -r '.answer' <<<"$HTTP_BODY") ]] || fail "语料 #$index 回答为空：$HTTP_BODY"
    if [[ -n $intent ]]; then
      [[ $(jq -r '.intent' <<<"$HTTP_BODY") == "$intent" ]] \
        || fail "语料 #$index 意图期望 $intent，实际 $(jq -r '.intent' <<<"$HTTP_BODY")"
    fi
    ANSWERED=$((ANSWERED + 1))
    [[ -n $RID_QUERY ]] || RID_QUERY=$rid
    continue
  fi
  [[ $expect == *unlicensed* || $expect == *forbidden* ]] \
    || fail "语料 #$index 期望 $expect，却返回 answerable=false：$HTTP_BODY"
  [[ $(jq -r '.citations | length' <<<"$HTTP_BODY") == "0" ]] \
    || fail "语料 #$index 拒答仍带引用：$HTTP_BODY"
  [[ -n $(jq -r '.reason' <<<"$HTTP_BODY") ]] || fail "语料 #$index 拒答缺 reason：$HTTP_BODY"
done <"$READ_CASES"
[[ -n $RID_QUERY ]] || fail "语料没有可作答用例，审计步骤无法继续"
read_total=$(wc -l <"$READ_CASES" | tr -d ' ')
step_end 200 "语料 $read_total 条只读/拒答用例：answered=$ANSWERED；拒答不带引用"
ARTIFACT_ENTRIES+=("$(jq -n --argjson a "$ANSWERED" --argjson t "$read_total" \
  '{query_corpus_read:{cases:$t, answered:$a}}')")

# ---------------------------------------------------------------- 步骤 7

step_begin 7 "写意图边界：语料中的 forbidden 用例不产生订单"
http GET "/execution/orders?limit=200"
expect_status 200
orders_before=$(jq -r '.items | length' <<<"$HTTP_BODY")
RID_WRITE=""
while IFS=$'\t' read -r index expect intent body; do
  [[ -n $index ]] || continue
  [[ $intent == "-" ]] && intent=""
  rid="p4-smoke-$RUN_TAG-w$index"
  http POST /ai/query "$body" "$rid"
  if [[ $HTTP_STATUS == "403" ]]; then
    [[ $(jq -r '.error.code' <<<"$HTTP_BODY") == "ai_write_forbidden" ]] \
      || fail "语料 #$index 403 但错误码不是 ai_write_forbidden：$HTTP_BODY"
    [[ -n $RID_WRITE ]] || RID_WRITE=$rid
    continue
  fi
  expect_status 200
  [[ $(jq -r '.answerable' <<<"$HTTP_BODY") == "false" ]] \
    || fail "语料 #$index 写请求被作答：$HTTP_BODY"
  [[ $(jq -r '.citations | length' <<<"$HTTP_BODY") == "0" ]] \
    || fail "语料 #$index 写请求仍带引用：$HTTP_BODY"
done <"$WRITE_CASES"
[[ -n $RID_WRITE ]] || fail "语料没有触发 403 的写用例，审计步骤无法继续"
http GET "/execution/orders?limit=200"
expect_status 200
orders_after=$(jq -r '.items | length' <<<"$HTTP_BODY")
[[ $orders_after == "$orders_before" ]] || fail "写意图后订单数变化：$orders_before -> $orders_after"
write_total=$(wc -l <"$WRITE_CASES" | tr -d ' ')
step_end 403 "语料 $write_total 条写用例全部被拒；订单数保持 $orders_after"
ARTIFACT_ENTRIES+=("$(jq -n --argjson t "$write_total" '{query_corpus_write:{cases:$t}}')")

# ---------------------------------------------------------------- 步骤 8

step_begin 8 "审计：每次调用一条 ops.audit_log，重放不重复"
audit_rows=$(
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "${POSTGRES_USER:-trading}" -d "${POSTGRES_DB:-trading}" -At -F '|' -c \
    "select request_id, action, resource, coalesce(after->>'outcome','') from ops.audit_log
     where actor='ai' and request_id like 'p4-smoke-$RUN_TAG-%'
     order by request_id, id;"
) || fail "查询 ops.audit_log 失败"
[[ -n $audit_rows ]] || fail "没有找到本轮的 ai 审计记录"
check_audit() {
  local rid=$1 action=$2 resource=$3 outcome=$4 count
  count=$(grep -c "^$rid|$action|$resource|$outcome$" <<<"$audit_rows" || true)
  [[ $count == "1" ]] || fail "审计 $rid 期望 1 条（$action/$resource/$outcome），实际 $count；全部：$audit_rows"
}
check_audit "$RID_MARKET" ai.explain.market market ok
check_audit "$RID_RELATIONS" ai.explain.relations target ok
check_audit "$RID_STRATEGY" ai.explain.strategy strategy ok
check_audit "$RID_BACKTEST" ai.explain.backtest backtest ok
check_audit "$RID_QUERY" ai.query query ok
check_audit "$RID_WRITE" ai.query query forbidden
step_end 200 "6 个请求 6 条审计；market 重放未重复记账"
ARTIFACT_ENTRIES+=("$(jq -n --arg rows "$audit_rows" '{audit_rows:($rows|split("\n"))}')")

# ---------------------------------------------------------------- 汇总

printf '\n%-4s %-46s %-6s %-9s %s\n' "步骤" "内容" "HTTP" "耗时(ms)" "结论"
for row in "${SUMMARY_ROWS[@]}"; do
  IFS='|' read -r n name code ms note <<<"$row"
  printf '%-4s %-46s %-6s %-9s %s\n' "$n" "$name" "$code" "$ms" "$note"
done

mkdir -p "$(dirname "$ARTIFACT")"
printf '%s\n' "${ARTIFACT_ENTRIES[@]}" | jq -s \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg api "$API_BASE" --arg tag "$RUN_TAG" \
  '{generated_at:$ts, api_base:$api, run_tag:$tag, ai_provider:"rule_based", real_trading_enabled:false, steps:.}' \
  >"$ARTIFACT" || fail "写入验收产物失败：$ARTIFACT"
printf '\n验收产物：%s\n' "${ARTIFACT#"$REPO_ROOT"/}"
step_end 200 "全链路通过（只读助手，外部模型未启用）"
