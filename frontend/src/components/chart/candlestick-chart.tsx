import {
  CANDLE_CHART_HEIGHT,
  CANDLE_CHART_WIDTH,
  buildCandlestickChart,
  type CandlestickInput,
} from "../../lib/candlestick";
import { cn } from "../../lib/utils";

const UP_COLOR =
  "stroke-emerald-600 fill-emerald-600 dark:stroke-emerald-400 dark:fill-emerald-400";
const DOWN_COLOR = "stroke-rose-600 fill-rose-600 dark:stroke-rose-400 dark:fill-rose-400";
const OVERLAY_COLORS: Record<string, string> = {
  MA20: "stroke-sky-500",
  MA60: "stroke-amber-500",
};

export type CandlestickChartProps = {
  data: CandlestickInput;
  label?: string;
  className?: string;
};

/**
 * 蜡烛图 + 成交量 + 均线 + 缺口标记。
 *
 * 所有数值由后端聚合接口给出，组件只负责画图。
 */
export function CandlestickChart({
  data,
  label = "K 线图",
  className,
}: CandlestickChartProps) {
  const geometry = buildCandlestickChart(data);

  if (geometry.candles.length === 0) {
    return (
      <p className={cn("py-12 text-center text-sm text-muted-foreground", className)}>
        尚未同步
      </p>
    );
  }

  return (
    <svg
      className={cn("w-full", className)}
      viewBox={`0 0 ${CANDLE_CHART_WIDTH} ${CANDLE_CHART_HEIGHT}`}
      role="img"
      aria-label={`${label}，共 ${geometry.candles.length} 根 K 线`}
    >
      {geometry.priceTicks.map((tick) => (
        <g key={`price-${tick.y}`}>
          <line
            x1={geometry.plotLeft}
            x2={geometry.plotRight}
            y1={tick.y}
            y2={tick.y}
            strokeDasharray="3 5"
            className="stroke-border"
          />
          <text
            x={geometry.plotLeft - 8}
            y={tick.y + 4}
            textAnchor="end"
            className="fill-muted-foreground text-[11px]"
          >
            {tick.label}
          </text>
        </g>
      ))}

      {geometry.gaps.map((gap) => (
        <g key={`gap-${gap.left}-${gap.right}`}>
          <rect
            x={gap.left}
            y={geometry.priceTop}
            width={gap.right - gap.left}
            height={geometry.volumeBottom - geometry.priceTop}
            className="fill-amber-500/10"
          >
            <title>{`缺口 ${gap.missing} 根`}</title>
          </rect>
          <line
            x1={gap.left}
            x2={gap.left}
            y1={geometry.priceTop}
            y2={geometry.volumeBottom}
            strokeDasharray="2 4"
            className="stroke-amber-500/50"
          />
          {gap.right - gap.left >= 24 ? (
            <text
              x={(gap.left + gap.right) / 2}
              y={geometry.priceTop + 12}
              textAnchor="middle"
              className="fill-amber-600 text-[10px] dark:fill-amber-400"
            >
              缺口 {gap.missing}
            </text>
          ) : null}
        </g>
      ))}

      {geometry.candles.map((candle) => (
        <g key={candle.time}>
          <line
            x1={candle.x}
            x2={candle.x}
            y1={candle.highY}
            y2={candle.lowY}
            strokeWidth={1}
            className={candle.up ? UP_COLOR : DOWN_COLOR}
          />
          <rect
            x={candle.bodyX}
            y={candle.bodyTop}
            width={candle.bodyWidth}
            height={candle.bodyBottom - candle.bodyTop}
            className={candle.up ? UP_COLOR : DOWN_COLOR}
          />
          <rect
            x={candle.bodyX}
            y={candle.volumeY}
            width={candle.bodyWidth}
            height={candle.volumeHeight}
            className={candle.up ? "fill-emerald-600/30" : "fill-rose-600/30"}
          />
        </g>
      ))}

      {geometry.overlays.map((overlay) => (
        <path
          key={overlay.name}
          d={overlay.path}
          fill="none"
          strokeWidth={1.4}
          strokeLinejoin="round"
          strokeLinecap="round"
          className={OVERLAY_COLORS[overlay.name] ?? "stroke-muted-foreground"}
        />
      ))}

      <line
        x1={geometry.plotLeft}
        x2={geometry.plotRight}
        y1={geometry.volumeBottom}
        y2={geometry.volumeBottom}
        className="stroke-border"
      />

      {geometry.timeTicks.map((tick) => (
        <text
          key={`time-${tick.x}`}
          x={tick.x}
          y={CANDLE_CHART_HEIGHT - 10}
          textAnchor={tick.anchor}
          className="fill-muted-foreground text-[11px]"
        >
          {tick.label}
        </text>
      ))}
    </svg>
  );
}
