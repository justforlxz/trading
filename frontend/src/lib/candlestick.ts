/**
 * K 线图的几何计算。
 *
 * 只把后端返回的开高低收、均线和缺口摆到 SVG 坐标上，不计算任何指标，
 * 不补齐缺失的 K 线，也不改变数值。
 */

import type { InstrumentAnalysisCandle, InstrumentAnalysisCandles } from "./api";
import { formatBeijingTime } from "./display";

export const CANDLE_CHART_WIDTH = 960;
export const CANDLE_CHART_HEIGHT = 380;

const PLOT_LEFT = 64;
const PLOT_RIGHT = CANDLE_CHART_WIDTH - 16;
const PRICE_TOP = 14;
const PRICE_BOTTOM = 252;
const VOLUME_TOP = 272;
const VOLUME_BOTTOM = 332;
const PRICE_PADDING_RATIO = 0.06;
const PRICE_TICK_COUNT = 5;
const TIME_TICK_LIMIT = 6;

export type CandleGeometry = {
  time: string;
  x: number;
  bodyX: number;
  bodyWidth: number;
  bodyTop: number;
  bodyBottom: number;
  highY: number;
  lowY: number;
  up: boolean;
  volumeY: number;
  volumeHeight: number;
};

export type OverlayGeometry = {
  name: string;
  path: string;
};

export type GapGeometry = {
  left: number;
  right: number;
  missing: number;
};

export type PriceTick = { y: number; label: string };
export type TimeTick = { x: number; label: string; anchor: "start" | "middle" | "end" };

export type CandlestickGeometry = {
  plotLeft: number;
  plotRight: number;
  priceTop: number;
  priceBottom: number;
  volumeTop: number;
  volumeBottom: number;
  candles: CandleGeometry[];
  overlays: OverlayGeometry[];
  gaps: GapGeometry[];
  priceTicks: PriceTick[];
  timeTicks: TimeTick[];
};

export type CandlestickInput = Pick<InstrumentAnalysisCandles, "candles" | "overlays" | "gaps">;

function parseNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function tickDigits(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 2;
  return Math.min(8, Math.max(0, Math.ceil(-Math.log10(step))));
}

export function emptyCandlestickGeometry(): CandlestickGeometry {
  return {
    plotLeft: PLOT_LEFT,
    plotRight: PLOT_RIGHT,
    priceTop: PRICE_TOP,
    priceBottom: PRICE_BOTTOM,
    volumeTop: VOLUME_TOP,
    volumeBottom: VOLUME_BOTTOM,
    candles: [],
    overlays: [],
    gaps: [],
    priceTicks: [],
    timeTicks: [],
  };
}

type PricedCandle = {
  candle: InstrumentAnalysisCandle;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function pricedCandles(candles: InstrumentAnalysisCandle[]): PricedCandle[] {
  return candles
    .map((candle) => {
      const open = parseNumber(candle.open);
      const high = parseNumber(candle.high);
      const low = parseNumber(candle.low);
      const close = parseNumber(candle.close);
      const volume = parseNumber(candle.volume);
      if (open === null || high === null || low === null || close === null) return null;
      return { candle, open, high, low, close, volume: volume ?? 0 };
    })
    .filter((row): row is PricedCandle => row !== null);
}

export function buildCandlestickChart(input: CandlestickInput): CandlestickGeometry {
  const priced = pricedCandles(input.candles);
  if (priced.length === 0) return emptyCandlestickGeometry();

  const overlayValues = input.overlays.flatMap((overlay) =>
    overlay.points
      .map((point) => parseNumber(point.value))
      .filter((value): value is number => value !== null),
  );
  const rawLow = Math.min(...priced.map((row) => row.low), ...overlayValues);
  const rawHigh = Math.max(...priced.map((row) => row.high), ...overlayValues);
  const span = rawHigh - rawLow;
  const padding =
    span > 0 ? span * PRICE_PADDING_RATIO : Math.max(Math.abs(rawHigh) * 0.01, 0.01);
  const priceLow = rawLow - padding;
  const priceHigh = rawHigh + padding;
  const priceSpan = priceHigh - priceLow;
  const priceHeight = PRICE_BOTTOM - PRICE_TOP;
  const yFor = (price: number) => PRICE_TOP + ((priceHigh - price) / priceSpan) * priceHeight;

  const slotWidth = (PLOT_RIGHT - PLOT_LEFT) / priced.length;
  const bodyWidth = Math.max(1, Math.min(14, slotWidth * 0.58));
  const xFor = (index: number) => PLOT_LEFT + slotWidth * (index + 0.5);
  const maxVolume = Math.max(...priced.map((row) => row.volume), 0);

  const candles: CandleGeometry[] = priced.map((row, index) => {
    const top = yFor(Math.max(row.open, row.close));
    const bottom = yFor(Math.min(row.open, row.close));
    const volumeHeight =
      maxVolume > 0 ? (row.volume / maxVolume) * (VOLUME_BOTTOM - VOLUME_TOP) : 0;
    return {
      time: row.candle.open_time,
      x: round(xFor(index)),
      bodyX: round(xFor(index) - bodyWidth / 2),
      bodyWidth: round(bodyWidth),
      bodyTop: round(top),
      bodyBottom: round(Math.max(bottom, top + 1)),
      highY: round(yFor(row.high)),
      lowY: round(yFor(row.low)),
      up: row.close >= row.open,
      volumeY: round(VOLUME_BOTTOM - volumeHeight),
      volumeHeight: round(volumeHeight),
    };
  });

  const indexByTime = new Map(candles.map((candle, index) => [candle.time, index]));
  const overlays: OverlayGeometry[] = input.overlays
    .map((overlay) => {
      const points = overlay.points
        .map((point) => {
          const index = indexByTime.get(point.time);
          const value = parseNumber(point.value);
          if (index === undefined || value === null) return null;
          return { x: candles[index].x, y: yFor(value) };
        })
        .filter((point): point is { x: number; y: number } => point !== null);
      const path = points
        .map(
          (point, index) =>
            `${index === 0 ? "M" : "L"}${round(point.x)} ${round(point.y)}`,
        )
        .join(" ");
      return { name: overlay.name, path };
    })
    .filter((overlay) => overlay.path !== "");

  const times = candles.map((candle) => Date.parse(candle.time));
  const gaps: GapGeometry[] = [];
  for (const gap of input.gaps) {
    const gapStart = Date.parse(gap.start);
    const gapEnd = Date.parse(gap.end);
    if (Number.isNaN(gapStart) || Number.isNaN(gapEnd)) continue;
    let before = -1;
    let after = -1;
    times.forEach((time, index) => {
      if (time < gapStart) before = index;
      if (time >= gapEnd && after === -1) after = index;
    });
    const rawLeft = before === -1 ? PLOT_LEFT : candles[before].x + slotWidth / 2;
    const rawRight = after === -1 ? PLOT_RIGHT : candles[after].x - slotWidth / 2;
    // 缺口两侧的 K 线在数组里相邻，按索引等距摆放时会重合；保留一条可见的标记带。
    const center = (rawLeft + rawRight) / 2;
    const left = rawRight - rawLeft < 24 ? Math.max(PLOT_LEFT, center - 12) : rawLeft;
    const right = rawRight - rawLeft < 24 ? Math.min(PLOT_RIGHT, center + 12) : rawRight;
    if (right <= left) continue;
    gaps.push({ left: round(left), right: round(right), missing: gap.missing });
  }

  const priceStep = priceSpan / (PRICE_TICK_COUNT - 1);
  const digits = tickDigits(priceStep);
  const priceTicks = Array.from({ length: PRICE_TICK_COUNT }, (_, index) => ({
    y: round(PRICE_TOP + (priceHeight * index) / (PRICE_TICK_COUNT - 1)),
    label: (priceHigh - priceStep * index).toFixed(digits),
  }));

  const tickCount = Math.min(candles.length, TIME_TICK_LIMIT);
  const timeTicks =
    tickCount === 1
      ? [
          {
            x: candles[0].x,
            label: formatBeijingTime(candles[0].time, false),
            anchor: "middle" as const,
          },
        ]
      : Array.from({ length: tickCount }, (_, index) => {
          const target = Math.round(((candles.length - 1) * index) / (tickCount - 1));
          return {
            x: candles[target].x,
            label: formatBeijingTime(candles[target].time, false),
            anchor:
              index === 0 ? ("start" as const) : index === tickCount - 1 ? ("end" as const) : ("middle" as const),
          };
        });

  return {
    plotLeft: PLOT_LEFT,
    plotRight: PLOT_RIGHT,
    priceTop: PRICE_TOP,
    priceBottom: PRICE_BOTTOM,
    volumeTop: VOLUME_TOP,
    volumeBottom: VOLUME_BOTTOM,
    candles,
    overlays,
    gaps,
    priceTicks,
    timeTicks,
  };
}
