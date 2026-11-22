/**
 * 宏观读数的展示纯函数。
 *
 * 状态、数值、时间、延迟标记与分级都由后端给出；这里只把契约枚举换成中文、把同一
 * 序列的分钟级与日结值挑出用于展示的那一条，并格式化利差的符号。不做任何业务计算：
 * 利差的基点是后端算好的，VIX 分级也是后端给的 `regime`。
 */

import type { MacroOverviewResponse, MacroReading, MacroSpread } from "./api";
import { signedValue } from "./display";

export type MacroGranularity = MacroReading["granularity"];
export type VixRegime = NonNullable<MacroReading["regime"]>;

const GRANULARITY_LABELS: Record<MacroGranularity, string> = {
  minute: "分钟级",
  daily: "日结",
};

const REGIME_LABELS: Record<VixRegime, string> = {
  low: "低波",
  normal: "常态",
  elevated: "偏高",
  panic: "恐慌",
};

const REGIME_TONES: Record<VixRegime, string> = {
  low: "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  normal: "border-border bg-muted/40 text-muted-foreground",
  elevated: "border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  panic: "border-rose-600/40 bg-rose-500/10 text-rose-700 dark:text-rose-400",
};

const QUALITY_LABELS: Record<MacroReading["quality_status"], string> = {
  normal: "正常",
  stale: "过期",
  missing: "缺失",
};

export function granularityLabel(granularity: MacroGranularity): string {
  return GRANULARITY_LABELS[granularity] ?? granularity;
}

export function regimeLabel(regime: VixRegime | null | undefined): string {
  return regime ? (REGIME_LABELS[regime] ?? regime) : "未分级";
}

export function regimeTone(regime: VixRegime | null | undefined): string {
  return regime ? (REGIME_TONES[regime] ?? REGIME_TONES.normal) : REGIME_TONES.normal;
}

export function macroQualityLabel(status: MacroReading["quality_status"]): string {
  return QUALITY_LABELS[status] ?? status;
}

/** 取某个序列某个粒度的读数；没有这一行时返回 `null`。 */
export function readingOf(
  overview: MacroOverviewResponse | null,
  seriesId: string,
  granularity: MacroGranularity,
): MacroReading | null {
  if (overview === null) return null;
  return (
    overview.readings.find(
      (item) => item.series_id === seriesId && item.granularity === granularity,
    ) ?? null
  );
}

/**
 * 展示用的那一条：优先分钟级，分钟级缺失时退回日结值。
 *
 * 两种粒度的时间与延迟标记各自独立，退回时调用方按 `granularity` 标注「日结」，不把
 * 日结值写成分钟级时间。
 */
export function primaryReading(
  overview: MacroOverviewResponse | null,
  seriesId: string,
): MacroReading | null {
  const minute = readingOf(overview, seriesId, "minute");
  if (minute !== null && minute.value !== null) return minute;
  return readingOf(overview, seriesId, "daily") ?? minute;
}

/** 关注列表只关心全局风险读数：VIX。 */
export function vixReading(overview: MacroOverviewResponse | null): MacroReading | null {
  return primaryReading(overview, "vix");
}

/** 读数是否有值；`null` 表示这一行缺数据，页面写「缺失」并给原因。 */
export function hasValue(reading: MacroReading | null): boolean {
  return reading !== null && reading.value !== null;
}

/** 数值 + 单位；没有值时给 `null`，由调用方决定写「缺失」。 */
export function readingValueText(reading: MacroReading | null): string | null {
  if (reading === null || reading.value === null) return null;
  return `${reading.value}${reading.unit}`;
}

/** 日变化：正数补 `+`，负数为「倒挂」之外的普通涨跌，与股票涨跌同一套符号规则。 */
export function changeText(reading: MacroReading | null): string | null {
  if (reading === null || reading.change == null) return null;
  return `${signedValue(reading.change)}${reading.unit}`;
}

/** 利差显示：`+29bp` / `-53bp`；不可用时给原因。倒挂由后端 `inverted` 决定。 */
export function spreadValueText(spread: MacroSpread | null): string | null {
  if (spread === null || !spread.available || spread.value_bp == null) return null;
  return `${signedValue(spread.value_bp)}bp`;
}

export function spreadUnavailableText(spread: MacroSpread | null): string | null {
  if (spread === null) return "利差不可用";
  if (spread.available) return null;
  return spread.reason?.trim() ? spread.reason : "利差不可用";
}

export function spreadTone(spread: MacroSpread | null): string {
  if (spread === null || !spread.available) return "text-muted-foreground";
  return spread.inverted ? "text-rose-600 dark:text-rose-400" : "text-foreground";
}

/** 总览级过期提示；`stale_reason` 为空时仍明确说明不能当作实时值。 */
export function macroStaleNotice(overview: MacroOverviewResponse | null): string | null {
  if (overview === null || !overview.stale) return null;
  const reason = overview.stale_reason?.trim();
  return reason ? `宏观数据已过期：${reason}` : "宏观数据已过期，不能当作实时值。";
}

/** 延迟标记：只有后端说 `is_delayed` 才是延迟，不按来源名猜。 */
export function delayLabel(reading: MacroReading | null): string | null {
  if (reading === null) return null;
  return reading.is_delayed ? "延迟" : "实时";
}
