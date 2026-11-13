/**
 * 自选页的展示规则：分类筛选、中文标签与缺数据文案。
 *
 * 这里不计算任何业务数值：趋势、RSI、ATR、K 线覆盖都来自后端契约字段，
 * 本模块只做分类判断、枚举翻译与缺失值的显式文案。
 */

import type { InstrumentRef, WatchlistItem } from "./api";

export type WatchlistCategory = "all" | "stock_swap" | "crypto";

export const WATCHLIST_CATEGORIES: ReadonlyArray<{
  value: WatchlistCategory;
  label: string;
}> = [
  { value: "all", label: "全部" },
  { value: "stock_swap", label: "股票永续" },
  { value: "crypto", label: "加密" },
];

type InstrumentLike = Pick<InstrumentRef, "asset_type" | "inst_type">;
type DataStatus = WatchlistItem["data_status"];
type Trend = WatchlistItem["trend"];

const ASSET_TYPE_LABELS: Record<InstrumentRef["asset_type"], string> = {
  tokenized_equity: "代币化股票",
  crypto: "加密资产",
  commodity_token: "代币化商品",
  unknown: "未分类",
};

/** 分类是页面筛选，不改变后端返回的标的身份。 */
export function matchesCategory(instrument: InstrumentLike, category: WatchlistCategory): boolean {
  if (category === "all") return true;
  if (category === "stock_swap") {
    return instrument.asset_type === "tokenized_equity" && instrument.inst_type === "SWAP";
  }
  return instrument.asset_type === "crypto";
}

export function assetTypeLabel(assetType: InstrumentRef["asset_type"]): string {
  return ASSET_TYPE_LABELS[assetType];
}

export function trendLabel(trend: Trend): string {
  if (trend === "bullish") return "偏多";
  if (trend === "bearish") return "偏空";
  if (trend === "neutral") return "中性";
  return "未生成";
}

export function trendTone(trend: Trend): string {
  if (trend === "bullish") return "text-emerald-600 dark:text-emerald-400";
  if (trend === "bearish") return "text-rose-600 dark:text-rose-400";
  return "text-muted-foreground";
}

/** 缺数据分两种：没有 K 线写“尚未同步”，有 K 线但算不出写“未生成”。 */
export function metricText(value: string | null, status: DataStatus): string {
  if (value !== null) return value;
  return status === "missing" ? "尚未同步" : "未生成";
}

export function trendText(trend: Trend, status: DataStatus): string {
  if (trend !== null) return trendLabel(trend);
  return status === "missing" ? "尚未同步" : "未生成";
}

export function coverageText(item: Pick<WatchlistItem, "candle_count" | "data_status">): string {
  if (item.data_status === "missing") return "尚未同步";
  if (item.data_status === "partial") return `日线 ${item.candle_count} 根 · 指标待补`;
  return `日线 ${item.candle_count} 根`;
}

/** 契约时间是 UTC；列表只显示月日与时分，不把浏览器本地时区混进来。 */
export function shortUtc(iso: string | null): string {
  if (iso === null) return "尚未同步";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "尚未同步";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(
    date.getUTCMinutes(),
  )} UTC`;
}

export function dataTimeText(iso: string | null): string {
  return iso === null ? "尚未同步" : `最新日线 ${shortUtc(iso)}`;
}

/** 后端给的是 `[0,1]` 比率；这里只换成百分比显示，不重新计算比率。 */
export function ratioPercent(value: string | null): string {
  if (value === null) return "未生成";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${(number * 100).toFixed(0)}%`;
}
