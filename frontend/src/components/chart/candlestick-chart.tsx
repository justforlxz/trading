import {
  buildCandleChart,
  CHART_HEIGHT,
  CHART_WIDTH,
  type Candle,
} from "../../lib/chart";
import { cn } from "../../lib/utils";

/**
 * 手写 SVG K 线图。
 *
 * 只用契约返回的 OHLC 画蜡烛、价格刻度与时间刻度，不引入图表库，
 * 也不绘制任何契约之外的派生线（均线、成交量等随指标节点再谈）。
 */
export function CandlestickChart({
  candles,
  className,
}: {
  candles: Candle[];
  className?: string;
}) {
  const geometry = buildCandleChart(candles);

  if (geometry.boxes.length === 0) {
    return (
      <p className="rounded-md border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
        该周期暂无 K 线数据。
      </p>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={`K 线图，共 ${geometry.boxes.length} 根`}
      className={cn("h-auto w-full", className)}
    >
      {geometry.priceTicks.map((tick) => (
        <g key={`price-${tick.label}`}>
          <line
            x1={geometry.plotLeft}
            x2={geometry.plotRight}
            y1={tick.y}
            y2={tick.y}
            stroke="currentColor"
            strokeWidth={1}
            strokeDasharray="3 4"
            className="text-border"
          />
          <text
            x={geometry.plotLeft - 8}
            y={tick.y + 3}
            textAnchor="end"
            fontSize={10}
            fill="currentColor"
            className="text-muted-foreground"
          >
            {tick.label}
          </text>
        </g>
      ))}

      {geometry.boxes.map((box) => (
        <g
          key={box.openTime}
          className={box.rising ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}
        >
          <line
            x1={box.centerX}
            x2={box.centerX}
            y1={box.wickTop}
            y2={box.wickBottom}
            stroke="currentColor"
            strokeWidth={1}
          />
          <rect
            x={box.bodyX}
            y={box.bodyTop}
            width={box.bodyWidth}
            height={box.bodyHeight}
            fill="currentColor"
          />
        </g>
      ))}

      {geometry.timeTicks.map((tick) => (
        <text
          key={`time-${tick.x}`}
          x={tick.x}
          y={geometry.plotBottom + 18}
          textAnchor="middle"
          fontSize={10}
          fill="currentColor"
          className="text-muted-foreground"
        >
          {tick.label}
        </text>
      ))}
    </svg>
  );
}
