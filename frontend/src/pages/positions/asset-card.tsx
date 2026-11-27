import { Card } from "../../components/ui/card";
import {
  amountText,
  curveGeometry,
  curveStroke,
  curveUnavailableText,
  EQUITY_RANGES,
  marginUsageFloorPrefix,
  notionalPrefix,
  percentText,
  signedAmountText,
  type AccountSummary,
  type EquityCurve,
  type EquityRange,
} from "../../lib/positions";
import { cn } from "../../lib/utils";

export type AssetCardViewProps = {
  account: AccountSummary | null;
  curve: EquityCurve | null;
  range: EquityRange;
  onRangeChange: (range: EquityRange) => void;
  loading: boolean;
};

const CHART_WIDTH = 720;
const CHART_HEIGHT = 72;

/**
 * 资产卡：当前权益 + 收益曲线 + 区间切换 + 一行次级指标。
 *
 * 曲线只用后端给的点。后端说「这段区间没有数据」时这里**一根折线都不画**：画一条
 * 被截断的线会让人以为十天就是一个月的全部行情。
 */
export function AssetCardView({
  account,
  curve,
  range,
  onRangeChange,
  loading,
}: AssetCardViewProps) {
  const geometry =
    curve === null ? null : curveGeometry(curve.points, CHART_WIDTH, CHART_HEIGHT);
  const change = curveChange(curve);
  const notionalPrefixText = notionalPrefix(account?.notional_status);

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          {/* 口径写清楚：这个数是 OKX 的账户权益 `totalEq`，不是「累计收益」。 */}
          <p className="text-[11px] text-muted-foreground">账户权益（OKX totalEq）</p>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-mono text-lg font-normal tabular-nums">
              {loading ? "读取中…" : amountText(account?.equity)}
            </span>
            <span className="text-xs text-muted-foreground">{account?.currency ?? "USDT"}</span>
            {change === null ? null : (
              <span className={cn("text-xs tabular-nums", change.tone)}>{change.text}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1" role="tablist" aria-label="收益曲线时间范围">
          {EQUITY_RANGES.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={item.key === range}
              onClick={() => onRangeChange(item.key)}
              className={cn(
                "h-7 rounded-md px-2 text-[11px] font-medium transition-colors",
                item.key === range
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-2">
        {geometry === null ? (
          <p
            className="rounded-md border px-3 py-6 text-center text-[11px] text-muted-foreground"
            data-curve-empty=""
          >
            {curve !== null && curve.available
              ? "读取曲线中…"
              : curveUnavailableText(curve?.first_snapshot_at)}
          </p>
        ) : (
          <svg
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            width="100%"
            height={CHART_HEIGHT}
            preserveAspectRatio="none"
            aria-hidden="true"
            data-curve-available=""
          >
            <polyline
              points={geometry.line}
              fill="none"
              stroke={curveStroke(geometry.direction)}
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </div>

      <p className="mt-1 text-[11px] text-muted-foreground">
        {curve === null
          ? "曲线来自账户快照（每分钟一条）"
          : curve.available
            ? `${rangeLabel(range)} · 基于账户快照（每分钟一条）`
            : "1 天 / 1 周为真实数据，月以上等快照积累"}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span>
          可用{" "}
          <span className="font-mono tabular-nums text-foreground">
            {amountText(account?.available_equity)}
          </span>{" "}
          {account?.currency ?? "USDT"}
        </span>
        <span>
          名义敞口{" "}
          <span className="font-mono tabular-nums text-foreground">
            {notionalPrefixText}
            {amountText(account?.gross_notional)}
          </span>
        </span>
        <span>
          已用保证金{" "}
          <span className="font-mono tabular-nums text-foreground">
            {amountText(account?.margin_used)}
          </span>
          <span className="ml-1 tabular-nums">
            ({marginUsageFloorPrefix(account?.margin_usage_floor)}
            {percentText(account?.margin_usage_pct)})
          </span>
        </span>
        <span>
          净敞口{" "}
          <span
            className={cn(
              "font-mono tabular-nums",
              netTone(account?.net_notional) ?? "text-foreground",
            )}
          >
            {signedAmountText(account?.net_notional)}
          </span>
        </span>
      </div>
    </Card>
  );
}

function rangeLabel(range: EquityRange): string {
  return EQUITY_RANGES.find((item) => item.key === range)?.label ?? range;
}

/**
 * 区间涨跌直接用后端的 `change_pct`。
 *
 * 前端不重算派生数字（`AGENTS.md` §6）：`(末 - 首) / 首` 是业务口径，改口径时应该
 * 只改一处。不足两点时后端给 `null`，这里就不显示，避免把单点当成 0%。
 */
function curveChange(curve: EquityCurve | null): { text: string; tone: string } | null {
  if (curve === null || curve.change_pct == null) return null;
  const pct = Number(curve.change_pct);
  if (!Number.isFinite(pct)) return null;
  return {
    text: `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`,
    tone:
      pct >= 0
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-rose-600 dark:text-rose-400",
  };
}

function netTone(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value.trim() === "-" || value === "") return null;
  return value.trim().startsWith("-")
    ? "text-rose-600 dark:text-rose-400"
    : "text-emerald-600 dark:text-emerald-400";
}

export default AssetCardView;
