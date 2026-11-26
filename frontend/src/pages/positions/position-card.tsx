import { Card } from "../../components/ui/card";
import {
  amountText,
  curveGeometry,
  curveStroke,
  percentText,
  positionSideLabel,
  priceText,
  signedAmountText,
  stopStatusLabel,
  stopStatusTone,
  uplRatioText,
  type PositionCard,
} from "../../lib/positions";
import { cn } from "../../lib/utils";

export type PositionCardViewProps = {
  card: PositionCard;
  onShowOrders: (instId: string) => void;
};

const SPARK_WIDTH = 132;
const SPARK_HEIGHT = 40;

/** 卡上要显示的止损说明：价位 + 距离，或三态里的另外两种。 */
function stopText(card: PositionCard): string {
  if (card.stop_status === "confirmed" && card.stop_px != null) {
    const distance =
      card.stop_distance_pct == null ? "" : ` 距 ${percentText(card.stop_distance_pct)}`;
    return `${priceText(card.stop_px)}${distance}`;
  }
  return stopStatusLabel(card.stop_status);
}

/**
 * 一张持仓卡片。
 *
 * 没有行情的持仓**保留卡片**：价格与盈亏位换成骨架占位并标「行情待同步」。整卡消失
 * 会让人以为这条持仓已经平掉，比显示空值危险得多。
 */
export function PositionCardView({ card, onShowOrders }: PositionCardViewProps) {
  const hasMarketData = card.mark_px != null;
  const weightWidth =
    card.weight_pct == null ? 0 : Math.max(0, Math.min(100, Number(card.weight_pct) || 0));
  const geometry = curveGeometry(card.upl_curve, SPARK_WIDTH, SPARK_HEIGHT);

  return (
    <Card className="p-3" data-position-card={card.pos_id}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs font-medium">{card.display_symbol}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {positionSideLabel(card.pos_side)}
            {card.lever === null ? null : ` · ${card.lever}x`}
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium",
            hasMarketData ? stopStatusTone(card.stop_status) : "border-border text-muted-foreground",
          )}
        >
          {hasMarketData ? stopStatusLabel(card.stop_status) : "行情待同步"}
        </span>
      </div>

      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="min-w-0">
          {hasMarketData ? (
            <>
              <p className="font-mono text-base font-normal tabular-nums">
                {priceText(card.mark_px)}
              </p>
              <p className={cn("text-[11px] tabular-nums", uplTone(card.upl))}>
                {signedAmountText(card.upl)}{" "}
                <span className="text-muted-foreground">({uplRatioText(card.upl_ratio)})</span>
              </p>
            </>
          ) : (
            <div className="w-full" data-skeleton="">
              <span className="block h-4 w-20 animate-pulse rounded bg-muted" />
              <span className="mt-1.5 block h-3 w-16 animate-pulse rounded bg-muted" />
            </div>
          )}
        </div>
        {hasMarketData && geometry !== null ? (
          <div className="flex shrink-0 flex-col items-end gap-1">
            <svg
              viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
              width={SPARK_WIDTH}
              height={SPARK_HEIGHT}
              aria-hidden="true"
              data-upl-curve=""
            >
              <polyline
                points={geometry.line}
                fill="none"
                stroke={curveStroke(geometry.direction)}
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <span className="text-[10px] text-muted-foreground">盈亏曲线</span>
          </div>
        ) : (
          <span
            className="block h-10 animate-pulse rounded bg-muted"
            style={{ width: SPARK_WIDTH }}
          />
        )}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span>
          名义{" "}
          <span className="font-mono tabular-nums text-foreground">
            {amountText(card.notional)}
          </span>
          {card.weight_pct == null ? null : (
            <span className="font-mono tabular-nums"> · {percentText(card.weight_pct)}</span>
          )}
        </span>
        {hasMarketData ? (
          <span className={card.stop_status === "none" ? "text-rose-600 dark:text-rose-400" : ""}>
            {stopText(card)}
          </span>
        ) : (
          <span className="block h-2.5 w-12 animate-pulse rounded bg-muted" />
        )}
      </div>

      <div className="mt-2 h-1 w-full rounded-full bg-muted">
        <div
          className="h-1 rounded-full bg-primary"
          style={{ width: `${weightWidth}%` }}
          aria-hidden="true"
        />
      </div>

      <button
        type="button"
        onClick={() => onShowOrders(card.inst_id)}
        className="mt-2 text-[11px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
      >
        查看订单历史
      </button>
    </Card>
  );
}

function uplTone(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") {
    return "text-muted-foreground";
  }
  return value.trim().startsWith("-")
    ? "text-rose-600 dark:text-rose-400"
    : "text-emerald-600 dark:text-emerald-400";
}

export default PositionCardView;
