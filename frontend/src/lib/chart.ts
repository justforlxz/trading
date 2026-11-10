/**
 * 分时折线图的几何计算。
 *
 * 只做「把收盘价摆到 SVG 坐标上」这一件呈现工作：不计算任何指标，
 * 也不补造缺失的点。
 */

import type { components } from "../api/types";

export type Candle = components["schemas"]["Candle"];

export const CHART_WIDTH = 800;
export const CHART_HEIGHT = 260;

const PLOT_LEFT = 64;
const PLOT_RIGHT = CHART_WIDTH - 16;
const PLOT_TOP = 12;
const PLOT_BOTTOM = CHART_HEIGHT - 28;
const PRICE_PADDING_RATIO = 0.08;
const PRICE_TICK_COUNT = 4;
const TIME_TICK_LIMIT = 6;

/** 折线上的一个点：时间取自 K 线，价格取自收盘价，原样保留字符串。 */
export type ClosePoint = {
  time: string;
  price: string;
};

export type PriceTick = { y: number; label: string };

export type TimeTick = { x: number; label: string };

export type LineChartGeometry = {
  plotLeft: number;
  plotRight: number;
  plotTop: number;
  plotBottom: number;
  points: Array<{ x: number; y: number; time: string }>;
  /** SVG 折线路径；价格无法解析的点不参与连线。 */
  line: string;
  priceTicks: PriceTick[];
  timeTicks: TimeTick[];
};

/** 只取收盘价，其余价格字段不进入界面。 */
export function closePoints(candles: Candle[]): ClosePoint[] {
  return candles.map((candle) => ({ time: candle.open_time, price: candle.close }));
}

function parsePrice(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function roundCoordinate(value: number): number {
  return Math.round(value * 100) / 100;
}

/** 相邻价格刻度之间的位数，只用于刻度文案。 */
function tickDigits(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 2;
  return Math.min(8, Math.max(0, Math.ceil(-Math.log10(step))));
}

/** 时间戳按契约以 UTC 表示，标签同样以 UTC 呈现，避免本地时区造成的歧义。 */
export function formatChartTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(
    date.getUTCHours(),
  )}:${pad(date.getUTCMinutes())}`;
}

function emptyGeometry(): LineChartGeometry {
  return {
    plotLeft: PLOT_LEFT,
    plotRight: PLOT_RIGHT,
    plotTop: PLOT_TOP,
    plotBottom: PLOT_BOTTOM,
    points: [],
    line: "",
    priceTicks: [],
    timeTicks: [],
  };
}

export function buildLineChart(closePrices: ClosePoint[]): LineChartGeometry {
  const priced = closePrices
    .map((point) => ({ time: point.time, price: parsePrice(point.price) }))
    .filter((point): point is { time: string; price: number } => point.price !== null);
  if (priced.length === 0) return emptyGeometry();

  const rawLow = Math.min(...priced.map((point) => point.price));
  const rawHigh = Math.max(...priced.map((point) => point.price));
  const span = rawHigh - rawLow;
  // 单点或全平盘没有跨度，用相对值撑开，保证除数恒大于 0。
  const padding = span > 0 ? span * PRICE_PADDING_RATIO : Math.max(Math.abs(rawHigh) * 0.01, 0.01);
  const priceLow = rawLow - padding;
  const priceHigh = rawHigh + padding;
  const priceSpan = priceHigh - priceLow;
  const plotHeight = PLOT_BOTTOM - PLOT_TOP;
  const yFor = (price: number) => PLOT_TOP + ((priceHigh - price) / priceSpan) * plotHeight;

  const slotWidth = (PLOT_RIGHT - PLOT_LEFT) / priced.length;
  const points = priced.map((point, index) => ({
    x: PLOT_LEFT + slotWidth * (index + 0.5),
    y: yFor(point.price),
    time: point.time,
  }));

  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${roundCoordinate(point.x)} ${roundCoordinate(point.y)}`)
    .join(" ");

  const priceStep = priceSpan / (PRICE_TICK_COUNT - 1);
  const digits = tickDigits(priceStep);
  const priceTicks = Array.from({ length: PRICE_TICK_COUNT }, (_, index) => ({
    y: PLOT_TOP + (plotHeight * index) / (PRICE_TICK_COUNT - 1),
    label: (priceHigh - priceStep * index).toFixed(digits),
  }));

  const tickCount = Math.min(points.length, TIME_TICK_LIMIT);
  const timeTicks =
    tickCount === 1
      ? [{ x: points[0].x, label: formatChartTime(points[0].time) }]
      : Array.from({ length: tickCount }, (_, index) => {
          const target = Math.round(((points.length - 1) * index) / (tickCount - 1));
          return { x: points[target].x, label: formatChartTime(points[target].time) };
        });

  return {
    plotLeft: PLOT_LEFT,
    plotRight: PLOT_RIGHT,
    plotTop: PLOT_TOP,
    plotBottom: PLOT_BOTTOM,
    points,
    line,
    priceTicks,
    timeTicks,
  };
}
