/**
 * 提醒的展示辅助。
 *
 * 标题、详情与级别全部来自接口；这里只做级别中文名、颜色和排序，
 * 不生成或推断任何提醒内容。
 */

import type { components } from "../api/types";

export type AlertItem = components["schemas"]["AlertItem"];
export type AlertListResponse = components["schemas"]["AlertListResponse"];
export type AlertType = AlertItem["type"];
export type AlertSeverity = AlertItem["severity"];
export type AlertStatus = AlertItem["status"];
export type AlertStatusUpdate = components["schemas"]["AlertStatusUpdateRequest"]["status"];

/** 首页提醒与详情页提醒共有的展示字段。 */
export type AlertView = {
  id: string;
  type: AlertType;
  severity?: string | null;
  instrument_id?: string | null;
  rule_id: string;
  title: string;
  detail: string;
  triggered_at: string;
};

const SEVERITY_LABELS: Record<string, string> = {
  critical: "严重",
  warning: "警告",
  info: "提示",
};

const TYPE_LABELS: Record<AlertType, string> = {
  indicator: "指标",
  price: "价格",
  risk: "风险",
  strategy: "策略",
  data: "数据",
};

const STATUS_LABELS: Record<AlertStatus, string> = {
  pending: "待处理",
  acknowledged: "已确认",
  ignored: "已忽略",
  expired: "已过期",
};

const SEVERITY_RANK: Record<string, number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

/** 未知级别原样显示，不猜成某一档。 */
export function severityLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return "未标注级别";
  return SEVERITY_LABELS[value] ?? value;
}

export function severityTone(value: string | null | undefined): string {
  if (value === "critical") return "border-rose-600/40 text-rose-700 dark:text-rose-300";
  if (value === "warning") return "border-amber-600/40 text-amber-700 dark:text-amber-300";
  if (value === "info") return "border-sky-600/40 text-sky-700 dark:text-sky-300";
  return "border-border text-muted-foreground";
}

export function alertTypeLabel(value: AlertType | string): string {
  return TYPE_LABELS[value as AlertType] ?? value;
}

export function alertStatusLabel(value: AlertStatus | string): string {
  return STATUS_LABELS[value as AlertStatus] ?? value;
}

/**
 * 严重在前，同一级别按触发时间倒序。只调整展示顺序，不改动接口返回的字段。
 */
export function sortAlertsBySeverity<T extends { severity?: string | null; triggered_at: string }>(
  items: ReadonlyArray<T>,
): T[] {
  return [...items].sort((left, right) => {
    const rank = (SEVERITY_RANK[left.severity ?? ""] ?? 3) - (SEVERITY_RANK[right.severity ?? ""] ?? 3);
    if (rank !== 0) return rank;
    return right.triggered_at.localeCompare(left.triggered_at);
  });
}

export type AlertFilters = {
  status?: AlertStatus;
  type?: AlertType;
  severity?: AlertSeverity;
  instrumentId?: string;
};

/** 只把实际设置过的条件写进查询串；标的筛选同时是详情提醒区的取数条件。 */
export function alertListQuery(filters: AlertFilters): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.status !== undefined) query.set("status", filters.status);
  if (filters.type !== undefined) query.set("type", filters.type);
  if (filters.severity !== undefined) query.set("severity", filters.severity);
  if (filters.instrumentId) query.set("instrument_id", filters.instrumentId);
  return query;
}
