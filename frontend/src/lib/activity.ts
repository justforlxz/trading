/**
 * 活动流水的筛选与事件类型中文名。
 *
 * 活动标题一律使用接口返回的 `summary`；这里只提供筛选条件和事件类型标签，
 * 让页面展示与 `GET /api/activity?event_type=...` 的结果保持一致。
 */

import type { components } from "../api/types";
import { beijingDayEndExclusiveIso, beijingDayStartIso } from "./journal";

export type ActivityItem = components["schemas"]["ActivityItem"];
export type ActivityListResponse = components["schemas"]["ActivityListResponse"];

/** 首页活动卡片与记录页活动列表共有的展示字段。 */
export type ActivityView = {
  id: string;
  event_type: string;
  summary: string;
  created_at: string;
};

export const ACTIVITY_EVENT_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "alert.created", label: "新提醒" },
  { value: "alert.acknowledged", label: "提醒已确认" },
  { value: "alert.ignored", label: "提醒已忽略" },
  { value: "alert.expired", label: "提醒已过期" },
  { value: "alert.reopened", label: "提醒重新触发" },
  { value: "research_note.created", label: "研究记录创建" },
  { value: "research_note.updated", label: "研究记录更新" },
  { value: "backtest.started", label: "回测开始" },
  { value: "backtest.completed", label: "回测完成" },
  { value: "backtest.failed", label: "回测失败" },
  { value: "strategy.created", label: "策略创建" },
  { value: "strategy.status_changed", label: "策略状态变更" },
  { value: "strategy.version_created", label: "策略版本创建" },
  { value: "watchlist.item.added", label: "加入自选" },
  { value: "watchlist.item.moved", label: "自选分组变更" },
  { value: "watchlist.item.removed", label: "移出自选" },
  { value: "position.manual.created", label: "手动持仓创建" },
  { value: "position.manual.updated", label: "手动持仓更新" },
  { value: "position.manual.deleted", label: "手动持仓删除" },
  { value: "position.manual.trade_added", label: "手动持仓流水新增" },
  { value: "account.sync.succeeded", label: "账户同步成功" },
  { value: "account.sync.failed", label: "账户同步失败" },
  { value: "data_source.connected", label: "数据源连接" },
  { value: "data_source.disconnected", label: "数据源断开" },
  { value: "data_source.reconnected", label: "数据源重连" },
];

/** 未知事件类型原样显示，便于核对后端新增的类型。 */
export function activityEventLabel(value: string): string {
  return ACTIVITY_EVENT_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export type ActivityFilters = {
  eventType?: string;
  objectType?: string;
  /** 起始日期（北京时间，含当天）。 */
  from?: string;
  /** 截止日期（北京时间，含当天）。 */
  to?: string;
};

/** 日期按北京时间当天换算成 UTC ISO；只写实际设置过的筛选条件。 */
export function activityQuery(filters: ActivityFilters): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.eventType) query.set("event_type", filters.eventType);
  if (filters.objectType) query.set("object_type", filters.objectType);
  if (filters.from) {
    const start = beijingDayStartIso(filters.from);
    if (start !== null) query.set("from", start);
  }
  if (filters.to) {
    const end = beijingDayEndExclusiveIso(filters.to);
    if (end !== null) query.set("to", end);
  }
  return query;
}
