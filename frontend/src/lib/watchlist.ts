/**
 * 自选页的展示规则：分组筛选、中文标签与缺数据文案。
 *
 * 这里不计算任何业务数值：趋势、RSI、ATR、K 线覆盖都来自后端契约字段，
 * 本模块只做分组判断、枚举翻译与缺失值的显式文案。
 */

import type { InstrumentRef, WatchlistItem } from "./api";

/** 没有指定分组时后端写入的分组名。 */
export const DEFAULT_GROUP = "默认";

/** 分组筛选的取值：`null` 表示「全部」。 */
export type WatchlistGroupFilter = string | null;

/** 筛选行与「移动到分组」只关心条目的 `group`，其余字段不参与。 */
type GroupedItem = Pick<WatchlistItem, "group">;

type DataStatus = WatchlistItem["data_status"];
type Trend = WatchlistItem["trend"];

const ASSET_TYPE_LABELS: Record<InstrumentRef["asset_type"], string> = {
  tokenized_equity: "代币化股票",
  crypto: "加密资产",
  commodity_token: "代币化商品",
  unknown: "未分类",
};

/**
 * 分组筛选行的分组名：接口返回的 `groups` 排在前面，再补上条目实际所在的分组，
 * 去重且保持首次出现的顺序。「全部」由页面单独渲染，不在这个列表里。
 *
 * 接口的 `groups` 是库里已有的全部分组，可能暂时没有条目；条目的 `group` 才是
 * 当前真实分布，两边合起来才不会漏掉任何一组。
 */
export function watchlistGroups(
  items: readonly GroupedItem[],
  groups: readonly string[],
): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  for (const raw of [...groups, ...items.map((item) => item.group)]) {
    const name = raw.trim();
    if (name === "" || seen.has(name)) continue;
    seen.add(name);
    names.push(name);
  }
  return names;
}

/** 分组筛选只看条目自己的 `group`；`null` 表示全部，不做其他归类。 */
export function matchesGroup(item: GroupedItem, group: WatchlistGroupFilter): boolean {
  return group === null || item.group === group;
}

/** 每个分组的条目数；接口列出的空分组记 0，不在筛选行里隐藏。 */
export function groupCounts(
  items: readonly GroupedItem[],
  groups: readonly string[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const name of watchlistGroups(items, groups)) counts[name] = 0;
  for (const item of items) counts[item.group] = (counts[item.group] ?? 0) + 1;
  return counts;
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
