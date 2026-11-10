/**
 * K 线图的几何计算。
 *
 * 只做「把契约里的十进制字符串摆到 SVG 坐标上」这一件呈现工作：
 * 不计算任何业务指标，也不补造缺失的 K 线。
 */

import type { components } from "../api/types";

export type Candle = components["schemas"]["Candle"];

export const CHART_WIDTH = 800;
export const CHART_HEIGHT = 320;

const PLOT_LEFT = 64;
const PLOT_RIGHT = CHART_WIDTH - 16;
const PLOT_TOP = 12;
const PLOT_BOTTOM = CHART_HEIGHT - 30;
const PRICE_PADDING_RATIO = 0.08;
const PRICE_TICK_COUNT = 5;
const TIME_TICK_LIMIT = 6;
const BODY_WIDTH_RATIO = 0.6;
const BODY_MIN_WIDTH = 2;
const BODY_MAX_WIDTH = 22;
const DOJI_HEIGHT = 1;

export type CandleBox = {
  centerX: number;
  bodyX: number;
  bodyWidth: number;
  bodyTop: number;
  bodyHeight: number;
  openY: number;
  closeY: number;
  wickTop: number;
  wickBottom: number;
  rising: boolean;
  openTime: string;
};

export type PriceTick = { y: number; label: string };

export type TimeTick = { x: number; label: string };

export type CandleChartGeometry = {
  plotLeft: number;
  plotRight: number;
  plotTop: number;
  plotBottom: number;
  boxes: CandleBox[];
  priceTicks: PriceTick[];
  timeTicks: TimeTick[];
};

function emptyGeometry(): CandleChartGeometry {
  return {
    plotLeft: PLOT_LEFT,
    plotRight: PLOT_RIGHT,
    plotTop: PLOT_TOP,
    plotBottom: PLOT_BOTTOM,
    boxes: [],
    priceTicks: [],
    timeTicks: [],
  };
}

/** 相邻价格刻度之间的位数，只用于刻度文案。 */
function tickDigits(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 2;
  return Math.min(8, Math.max(0, Math.ceil(-Math.log10(step))));
}

/** K 线时间戳按契约以 UTC 表示，标签同样以 UTC 呈现，避免本地时区造成的歧义。 */
export function formatCandleTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(
    date.getUTCHours(),
  )}:${pad(date.getUTCMinutes())}`;
}

export function buildCandleChart(candles: Candle[]): CandleChartGeometry {
  const isPrice = (value: string) => value.trim() !== "" && Number.isFinite(Number(value));
  const valid = candles.filter((candle) =>
    [candle.open, candle.high, candle.low, candle.close].every(isPrice),
  );
  if (valid.length === 0) return emptyGeometry();

  const lows = valid.map((candle) => Number(candle.low));
  const highs = valid.map((candle) => Number(candle.high));
  const rawLow = Math.min(...lows);
  const rawHigh = Math.max(...highs);
  const span = rawHigh - rawLow;
  // 单根或全平盘 K 线没有跨度，用相对值撑开，保证除数恒大于 0。
  const padding = span > 0 ? span * PRICE_PADDING_RATIO : Math.max(Math.abs(rawHigh) * 0.01, 0.01);
  const priceLow = rawLow - padding;
  const priceHigh = rawHigh + padding;
  const priceSpan = priceHigh - priceLow;
  const plotHeight = PLOT_BOTTOM - PLOT_TOP;
  const yFor = (price: number) => PLOT_TOP + ((priceHigh - price) / priceSpan) * plotHeight;

  const slotWidth = (PLOT_RIGHT - PLOT_LEFT) / valid.length;
  const bodyWidth = Math.min(
    BODY_MAX_WIDTH,
    Math.max(BODY_MIN_WIDTH, slotWidth * BODY_WIDTH_RATIO),
  );

  const boxes = valid.map((candle, index) => {
    const centerX = PLOT_LEFT + slotWidth * (index + 0.5);
    const openY = yFor(Number(candle.open));
    const closeY = yFor(Number(candle.close));
    const bodyTop = Math.min(openY, closeY);
    return {
      centerX,
      bodyX: centerX - bodyWidth / 2,
      bodyWidth,
      bodyTop,
      bodyHeight: Math.max(Math.abs(openY - closeY), DOJI_HEIGHT),
      openY,
      closeY,
      wickTop: yFor(Number(candle.high)),
      wickBottom: yFor(Number(candle.low)),
      rising: Number(candle.close) >= Number(candle.open),
      openTime: candle.open_time,
    };
  });

  const priceStep = priceSpan / (PRICE_TICK_COUNT - 1);
  const digits = tickDigits(priceStep);
  const priceTicks = Array.from({ length: PRICE_TICK_COUNT }, (_, index) => ({
    y: PLOT_TOP + (plotHeight * index) / (PRICE_TICK_COUNT - 1),
    label: (priceHigh - priceStep * index).toFixed(digits),
  }));

  const tickCount = Math.min(valid.length, TIME_TICK_LIMIT);
  const timeTicks =
    tickCount === 1
      ? [{ x: boxes[0].centerX, label: formatCandleTime(boxes[0].openTime) }]
      : Array.from({ length: tickCount }, (_, index) => {
          const target = Math.round(((valid.length - 1) * index) / (tickCount - 1));
          return { x: boxes[target].centerX, label: formatCandleTime(boxes[target].openTime) };
        });

  return {
    plotLeft: PLOT_LEFT,
    plotRight: PLOT_RIGHT,
    plotTop: PLOT_TOP,
    plotBottom: PLOT_BOTTOM,
    boxes,
    priceTicks,
    timeTicks,
  };
}
