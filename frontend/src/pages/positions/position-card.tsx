import { Card } from "../../components/ui/card";
import {
  amountText,
  curveGeometry,
  curveStroke,
  hasLiquidationPrice,
  instFormLabel,
  percentText,
  positionSideLabel,
  priceText,
  quoteTimeText,
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
 * 右上角徽标的文案与色调。
 *
 * 现货（`stop_supported=false`）没有止损概念：既不能说「未取到」（那是「问过、没问成」），
 * 也不能说「未挂止损」（那会让人去挂一张现货根本没有的委托）。
 */
function stopBadge(card: PositionCard): { text: string; tone: string } {
  if (!card.stop_supported) {
    return { text: "现货无止损", tone: "border-border text-muted-foreground" };
  }
  return { text: stopStatusLabel(card.stop_status), tone: stopStatusTone(card.stop_status) };
}

/** 卡片上的一行「标签 + 数值」。 */
function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

/**
 * 一张持仓卡片。
 *
 * 字段按用户给的清单：投入、收益（金额 + 百分比）、平均买入价、最新价格，合约再加
 * 强平价。名义价值与占比不展示——那是我们自己的权重口径，用户看不懂也不需要。
 *
 * 没有行情的持仓**保留卡片**：价格与盈亏位换成骨架占位并标「行情待同步」。整卡消失
 * 会让人以为这条持仓已经平掉，比显示空值危险得多。
 */
export function PositionCardView({ card, onShowOrders }: PositionCardViewProps) {
  const hasMarketData = card.mark_px != null;
  const geometry = curveGeometry(card.upl_curve, SPARK_WIDTH, SPARK_HEIGHT);
  // 没有行情时先报行情：那条结论比「有没有止损」更该先看到。
  const badge = hasMarketData
    ? stopBadge(card)
    : { text: "行情待同步", tone: "border-border text-muted-foreground" };
  const formLabel = instFormLabel(card.inst_type);
  // 同一页的价格可能来自交易所快照、日线收盘或实时报价；把时刻写出来，别让人以为都是当前价。
  const quoteTime = quoteTimeText(card.mark_px_at);
  return (
    <Card className="p-3" data-position-card={card.pos_id}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-baseline gap-1.5">
            <span className="truncate font-mono text-xs font-medium">{card.display_symbol}</span>
            {/* 现货与永续共用产品名，形态靠这个标签区分；标的没同步时不猜。 */}
            {formLabel === null ? null : (
              <span
                data-inst-form={formLabel}
                className="shrink-0 rounded border px-1 text-[10px] text-muted-foreground"
              >
                {formLabel}
              </span>
            )}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {positionSideLabel(card.pos_side)}
            {card.lever === null ? null : ` · ${card.lever}x`}
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium",
            badge.tone,
          )}
        >
          {badge.text}
        </span>
      </div>

      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="min-w-0">
          {hasMarketData ? (
            <>
              <p className={cn("font-mono text-base font-normal tabular-nums", uplTone(card.upl))}>
                {signedAmountText(card.upl)}{" "}
                <span className="text-[11px] text-muted-foreground">
                  ({uplRatioText(card.upl_ratio)})
                </span>
              </p>
              <p className="text-[10px] text-muted-foreground">收益</p>
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

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
        <Field label="投入" value={amountText(card.cost)} />
        <Field label="平均买入价" value={priceText(card.avg_px)} />
        <Field label="最新价格" value={priceText(card.mark_px)} />
        {/* 强平价只有合约有：现货没有杠杆，也就没有强平这回事。 */}
        {hasLiquidationPrice(card.inst_type) ? (
          <Field label="强平价" value={priceText(card.liq_px)} />
        ) : null}
      </dl>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span>{quoteTime ?? "—"}</span>
        {hasMarketData && card.stop_supported ? (
          <span className={card.stop_status === "none" ? "text-rose-600 dark:text-rose-400" : ""}>
            {stopText(card)}
          </span>
        ) : hasMarketData ? null : (
          <span className="block h-2.5 w-12 animate-pulse rounded bg-muted" />
        )}
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
