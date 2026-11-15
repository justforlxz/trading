/**
 * 记录页的纯展示与筛选辅助。
 *
 * 记录内容、标签与关联对象都保持接口返回的原值；这里只做中文标签、筛选字符串和
 * 数量统计，不生成、摘要或改写用户写下的正文。
 */

import type { components } from "../api/types";

export type ResearchNoteItem = components["schemas"]["ResearchNoteItem"];
export type ResearchNoteType = ResearchNoteItem["type"];
export type ResearchNoteSort = "created_at_desc" | "created_at_asc";

export const RESEARCH_NOTE_TYPE_OPTIONS: ReadonlyArray<{
  value: ResearchNoteType;
  label: string;
}> = [
  { value: "hypothesis", label: "假设" },
  { value: "backtest_conclusion", label: "回测结论" },
  { value: "decision", label: "决策" },
  { value: "review", label: "复盘" },
];

export const RESEARCH_NOTE_SORT_OPTIONS: ReadonlyArray<{
  value: ResearchNoteSort;
  label: string;
}> = [
  { value: "created_at_desc", label: "新到旧" },
  { value: "created_at_asc", label: "旧到新" },
];

export function researchNoteTypeLabel(value: ResearchNoteType | string): string {
  return RESEARCH_NOTE_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function researchNoteType(value: string | null | undefined): ResearchNoteType | null {
  if (value === null || value === undefined) return null;
  return RESEARCH_NOTE_TYPE_OPTIONS.some((option) => option.value === value)
    ? (value as ResearchNoteType)
    : null;
}

export type ResearchNoteFilters = {
  type?: ResearchNoteType;
  instrumentId?: string;
  strategyId?: string;
  backtestId?: string;
  /** 起始日期（北京时间，含当天）。 */
  from?: string;
  /** 截止日期（北京时间，含当天）。 */
  to?: string;
  sort?: ResearchNoteSort;
};

const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** 把 `YYYY-MM-DD` 解释为北京时间当天 00:00，返回 UTC ISO 字符串。 */
export function beijingDayStartIso(date: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date.trim());
  if (match === null) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const utcMidnight = Date.UTC(year, month - 1, day);
  const probe = new Date(utcMidnight);
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  ) {
    return null;
  }
  return new Date(utcMidnight - BEIJING_OFFSET_MS).toISOString();
}

/** 截止日期按「含当天」处理，因此返回次日 00:00（北京时间）的 UTC ISO。 */
export function beijingDayEndExclusiveIso(date: string): string | null {
  const start = beijingDayStartIso(date);
  if (start === null) return null;
  return new Date(Date.parse(start) + DAY_MS).toISOString();
}

/** 只把实际设置过的筛选条件写进查询串；日期按北京时间转换成带时区的 ISO。 */
export function researchNoteQuery(filters: ResearchNoteFilters): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.type !== undefined) query.set("type", filters.type);
  if (filters.instrumentId) query.set("related_instrument_id", filters.instrumentId);
  if (filters.strategyId) query.set("related_strategy_id", filters.strategyId);
  if (filters.backtestId) query.set("related_backtest_id", filters.backtestId);
  if (filters.from) {
    const start = beijingDayStartIso(filters.from);
    if (start !== null) query.set("from", start);
  }
  if (filters.to) {
    const end = beijingDayEndExclusiveIso(filters.to);
    if (end !== null) query.set("to", end);
  }
  if (filters.sort !== undefined) query.set("sort", filters.sort);
  return query;
}

/** 按当前接口返回的记录逐条计数，不推测未返回的记录。 */
export function countResearchNotesByType(
  items: ReadonlyArray<ResearchNoteItem>,
): Record<ResearchNoteType, number> {
  const counts: Record<ResearchNoteType, number> = {
    hypothesis: 0,
    backtest_conclusion: 0,
    decision: 0,
    review: 0,
  };
  for (const item of items) counts[item.type] += 1;
  return counts;
}

/** 标签输入用逗号或换行分隔，去空、去重并保持用户输入顺序。 */
export function parseResearchNoteTags(text: string): string[] {
  const tags: string[] = [];
  for (const part of text.split(/[,，\n]/)) {
    const tag = part.trim();
    if (tag !== "" && !tags.includes(tag)) tags.push(tag);
  }
  return tags;
}

export function joinResearchNoteTags(tags: ReadonlyArray<string>): string {
  return tags.join(", ");
}
