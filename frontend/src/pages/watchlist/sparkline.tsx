/**
 * 列表里的 24H 分时线：内联 SVG，不引图表库。
 *
 * 数据是最近 24 根 1 小时收盘（见 `index.tsx` 的取数）。少于两根真实收盘时画灰色虚线：
 * 一个点画不出走势，补假数据比留空更糟。
 */

const WIDTH = 76;
const HEIGHT = 30;
const PADDING = 3;

export function Sparkline({ closes }: { closes: readonly number[] }) {
  const usable = closes.filter((value) => Number.isFinite(value));

  if (usable.length < 2) {
    return (
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width={WIDTH}
        height={HEIGHT}
        aria-hidden="true"
        className="text-muted-foreground"
      >
        <line
          x1={PADDING}
          y1={HEIGHT / 2}
          x2={WIDTH - PADDING}
          y2={HEIGHT / 2}
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
      </svg>
    );
  }

  const min = Math.min(...usable);
  const max = Math.max(...usable);
  const span = max - min;
  const innerWidth = WIDTH - PADDING * 2;
  const innerHeight = HEIGHT - PADDING * 2;

  const point = (value: number, index: number): string => {
    const x = PADDING + (index * innerWidth) / (usable.length - 1);
    const ratio = span === 0 ? 0.5 : (value - min) / span;
    const y = HEIGHT - PADDING - ratio * innerHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };

  const line = usable.map(point).join(" ");
  const area = `${PADDING},${HEIGHT} ${line} ${WIDTH - PADDING},${HEIGHT}`;
  const tone =
    usable[usable.length - 1] >= usable[0]
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-destructive";

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width={WIDTH}
      height={HEIGHT}
      aria-hidden="true"
      fill="none"
      className={tone}
    >
      <polygon points={area} fill="currentColor" fillOpacity={0.07} />
      <polyline
        points={line}
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
