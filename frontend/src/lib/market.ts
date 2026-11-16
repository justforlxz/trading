/**
 * 市场概况与摘要展示的纯函数。
 *
 * 状态、来源和时间都来自接口；这里只把契约枚举换成中文，并把来源转成可点击的
 * 地址，不生成摘要文字，也不推断缺失数据的值。
 */

import type { components } from "../api/types";

export type MarketSnapshot = components["schemas"]["MarketSnapshotResponse"];
export type MarketOverviewItem = components["schemas"]["MarketOverviewItem"];
export type AiSummary = components["schemas"]["AiSummaryResponse"];
export type AiSummaryPoint = components["schemas"]["AiSummaryPoint"];
export type AiSummarySource = components["schemas"]["AiSummarySource"];

const SOURCE_LABELS: Record<AiSummarySource["type"], string> = {
  alert: "提醒",
  market_overview: "市场概况",
  risk: "风险",
};

/** 单个指标的延迟状态。缺失、过期与异常优先于「延迟」显示。 */
export function marketItemStatusLabel(item: MarketOverviewItem): string {
  if (item.quality_status === "stale") return "过期";
  if (item.quality_status === "missing") return "缺失";
  if (item.quality_status === "abnormal") return "异常";
  if (item.quality_status === "pending") return "等待中";
  if (item.is_delayed || item.quality_status === "delayed") return "延迟";
  return "实时";
}

/** 顶层过期提示；`stale_reason` 为空时仍明确说明不能当作实时值。 */
export function overviewStaleNotice(
  overview: { stale: boolean; stale_reason?: string | null },
): string | null {
  if (!overview.stale) return null;
  const reason = overview.stale_reason?.trim();
  return reason ? `数据已过期：${reason}` : "数据已过期，不能当作实时值。";
}

/** 每个事实点至少一条有标识的来源；没有来源的句子不展示。 */
export function pointsWithSources(points: readonly AiSummaryPoint[]): AiSummaryPoint[] {
  return points.filter((point) =>
    point.sources.some((source) => source.id.trim() !== ""),
  );
}

export function summarySourceLabel(type: AiSummarySource["type"]): string {
  return SOURCE_LABELS[type] ?? type;
}

/** 提醒、指标与风险点用页内锚点回到首页对应区块。 */
export function summarySourceHref(source: AiSummarySource): string | null {
  if (source.type === "alert") return "#alerts";
  if (source.type === "risk") return "#risk";
  if (source.type === "market_overview") return "#market-overview";
  return null;
}
