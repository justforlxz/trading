/**
 * 标的详情页的周期选择与数据覆盖区间文案。
 *
 * 周期顺序是页面行为的一部分：优先显示日线，避免固定 `1h` 时页面上四张指标卡
 * 全空。这里只做「按顺序探测」与时间文案，不计算任何指标。
 */

import type { CandleBar, InstrumentAnalysisBar } from "./api";

/** 有多个周期可看时优先 `1d`；自选列表的行情快照同样取日线。 */
export const DEFAULT_BAR_ORDER: CandleBar[] = ["1d", "4h", "1h", "15m", "5m", "1m"];

/**
 * 依次探测周期，返回第一个有 K 线的周期；所有周期都没有行情时回到 `1d`。
 *
 * 探测到结果就停止，不打后面的接口。
 */
export async function resolveDefaultBar(
  load: (bar: CandleBar) => Promise<{ candles: unknown[] }>,
): Promise<CandleBar> {
  for (const bar of DEFAULT_BAR_ORDER) {
    const series = await load(bar);
    if (series.candles.length > 0) return bar;
  }
  return DEFAULT_BAR_ORDER[0];
}

/**
 * 数据覆盖区间按 UTC 呈现；任一端缺失就不显示，避免把「不知道」写成具体区间。
 */
export function coverageLabel(from?: string | null, to?: string | null): string | null {
  if (!from || !to) return null;
  const start = formatUtc(from);
  const end = formatUtc(to);
  if (start === null || end === null) return null;
  return `${start} 至 ${end}`;
}

function formatUtc(value: string): string | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
  );
}

/**
 * 切换标的后保留当前周期：新标的没有该周期数据时，退回第一个有数据的周期。
 *
 * 覆盖顺序以后端返回为准（1d、4h、1h），所以优先回到日线，不把用户留在空图。
 */
export function resolveAvailableBar(
  coverage: ReadonlyArray<{ bar: InstrumentAnalysisBar; available: boolean }>,
  current: InstrumentAnalysisBar,
): InstrumentAnalysisBar {
  if (coverage.some((row) => row.bar === current && row.available)) return current;
  return coverage.find((row) => row.available)?.bar ?? current;
}
