/**
 * 市场概况、摘要与事件展示的纯函数。
 *
 * 状态、来源和时间都来自接口；这里只把契约枚举换成中文，并把来源转成可点击的
 * 地址，不生成摘要文字，也不推断缺失数据的值。
 */

import type { components } from "../api/types";

export type MarketSnapshot = components["schemas"]["MarketSnapshotResponse"];
export type MarketOverviewItem = components["schemas"]["MarketOverviewItem"];
export type MarketEvent = components["schemas"]["MarketEventItem"];
export type NewsArticle = components["schemas"]["NewsItem"];
export type AiSummary = components["schemas"]["AiSummaryResponse"];
export type AiSummaryPoint = components["schemas"]["AiSummaryPoint"];
export type AiSummarySource = components["schemas"]["AiSummarySource"];

export type EventGroup = "macro" | "earnings" | "announcement" | "other";

const EVENT_GROUP_LABELS: Record<EventGroup, string> = {
  macro: "宏观事件",
  earnings: "财报",
  announcement: "公告与新闻",
  other: "其他事件",
};

const EVENT_TYPE_LABELS: Record<string, string> = {
  macro: "宏观",
  economic: "宏观经济",
  economics: "宏观经济",
  economic_calendar: "宏观日历",
  earnings: "财报",
  earning: "财报",
  announcement: "公告",
  news: "新闻",
  dividend: "分红",
  stock_split: "拆股",
  split: "拆股",
  merger: "并购",
  ipo: "上市",
  filing: "申报文件",
  sec_filing: "监管申报",
  company_news: "公司新闻",
};

const MACRO_TYPES = new Set(["macro", "economic", "economics", "economic_calendar", "calendar"]);
const EARNINGS_TYPES = new Set(["earnings", "earning", "quarterly_earnings", "eps"]);
const ANNOUNCEMENT_TYPES = new Set([
  "announcement",
  "news",
  "company_news",
  "dividend",
  "stock_split",
  "split",
  "merger",
  "ipo",
  "filing",
  "sec_filing",
]);

const SOURCE_LABELS: Record<AiSummarySource["type"], string> = {
  news: "新闻",
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

/** 新闻回到原始链接；提醒、指标与风险点用页内锚点回到首页对应区块。 */
export function summarySourceHref(source: AiSummarySource): string | null {
  if (source.type === "news") return source.url ?? null;
  if (source.type === "alert") return "#alerts";
  if (source.type === "risk") return "#risk";
  if (source.type === "market_overview") return "#market-overview";
  return null;
}

export function eventGroup(eventType: string): EventGroup {
  const normalized = eventType.trim().toLowerCase();
  if (MACRO_TYPES.has(normalized)) return "macro";
  if (EARNINGS_TYPES.has(normalized)) return "earnings";
  if (ANNOUNCEMENT_TYPES.has(normalized)) return "announcement";
  return "other";
}

export function eventGroupLabel(group: EventGroup): string {
  return EVENT_GROUP_LABELS[group];
}

export function eventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABELS[eventType.trim().toLowerCase()] ?? eventType;
}

/** 详情页展示与当前产品相关的事件；没有绑定标的的宏观事件对所有产品可见。 */
export function eventsForTicker(
  events: readonly MarketEvent[],
  ticker: string,
): MarketEvent[] {
  const key = ticker.trim().toUpperCase();
  return events.filter(
    (event) => event.ticker === null || event.ticker.trim().toUpperCase() === key,
  );
}

/** 合并多次事件查询结果；同一 id 只保留第一次出现的记录。 */
export function mergeMarketEvents(
  ...groups: ReadonlyArray<readonly MarketEvent[]>
): MarketEvent[] {
  const byId = new Map<string, MarketEvent>();
  for (const group of groups) {
    for (const event of group) {
      if (!byId.has(event.id)) byId.set(event.id, event);
    }
  }
  return [...byId.values()];
}

export type MarketEventQuery = PromiseSettledResult<{ items: readonly MarketEvent[] }>;

/**
 * 合并按标的与全局发起的多次事件查询。
 * 任一路失败都保留失败原因，成功那一路的事件照常合并，避免部分失败被静默忽略。
 */
export function collectMarketEvents(results: readonly MarketEventQuery[]): {
  events: MarketEvent[];
  failures: unknown[];
} {
  const groups = results.map((result) =>
    result.status === "fulfilled" ? result.value.items : [],
  );
  const failures = results.flatMap((result) =>
    result.status === "rejected" ? [result.reason] : [],
  );
  return { events: mergeMarketEvents(...groups), failures };
}
