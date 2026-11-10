import { CHART_HEIGHT, CHART_WIDTH, buildLineChart, type ClosePoint } from "../../lib/chart";
import { cn } from "../../lib/utils";

export type LineChartProps = {
  points: ClosePoint[];
  className?: string;
};

/**
 * 收盘价折线。
 *
 * 只画一条线：没有蜡烛、影线、成交量、十字光标与缩放。
 */
export function LineChart({ points, className }: LineChartProps) {
  const geometry = buildLineChart(points);

  if (geometry.points.length === 0) {
    return (
      <p className={cn("py-10 text-center text-sm text-muted-foreground", className)}>
        该周期暂无收盘价数据。
      </p>
    );
  }

  return (
    <svg
      className={cn("w-full", className)}
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={`收盘价折线，共 ${geometry.points.length} 个点`}
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

      <path
        d={geometry.line}
        fill="none"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-sky-500"
      />

      {geometry.points.length === 1 ? (
        <circle
          cx={geometry.points[0].x}
          cy={geometry.points[0].y}
          r={2.5}
          className="fill-sky-500"
        />
      ) : null}

      {geometry.timeTicks.map((tick) => (
        <text
          key={`time-${tick.x}`}
          x={tick.x}
          y={CHART_HEIGHT - 8}
          textAnchor="middle"
          className="fill-muted-foreground text-[11px]"
        >
          {tick.label}
        </text>
      ))}
    </svg>
  );
}
