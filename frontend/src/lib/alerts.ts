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
  critical: "紧急",
  warning: "警告",
  info: "提示",
};

const TYPE_LABELS: Record<AlertType, string> = {
  indicator: "技术形态",
  price: "价格区间",
  risk: "持仓风险",
  strategy: "策略信号",
  data: "数据缺口",
};

/**
 * 提醒类型的中文标签，按「风险 → 信号 → 形态 → 价格 → 数据」排列。
 *
 * 与后端 `backend/app/events/sinks/render.py` 的 `TYPE_LABELS` 同一套措辞：同一条
 * 提醒在通知正文、提醒列表与设置页的复选框里必须是同一个说法。设置页直接用它渲染
 * 复选框，不再自己维护第二张表。
 */
export const ALERT_TYPE_OPTIONS: readonly { value: AlertType; label: string }[] = (
  ["risk", "strategy", "indicator", "price", "data"] as const
).map((value) => ({ value, label: TYPE_LABELS[value] }));

/** 提醒级别选项：与后端 `SEVERITY_LABELS` 同一套措辞，供设置页的下拉使用。 */
export const ALERT_SEVERITY_OPTIONS: readonly { value: string; label: string }[] = (
  ["info", "warning", "critical"] as const
).map((value) => ({ value, label: SEVERITY_LABELS[value] }));

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
