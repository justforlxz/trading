/**
 * 首页汇总的只读客户端、状态文案与推送合并。
 *
 * 所有数值都来自 `GET /api/dashboard/summary`；这里不重算盈亏、风险等级、
 * 覆盖率或摘要，只把契约里的字符串换单位、标状态，并按事件时间把推送值
 * 覆盖到 HTTP 快照上。
 */

import type { components } from "../api/types";
import { request } from "./api";
import { formatBeijingTime } from "./display";
import {
  isAtLeast,
  updateTime,
  type AccountUpdate,
  type PositionUpdate,
  type QuoteUpdate,
} from "./stream";

export type DashboardSummary = components["schemas"]["DashboardSummaryResponse"];
export type DashboardStatus = components["schemas"]["DashboardDegradedItem"]["status"];
export type DashboardDataSource = components["schemas"]["DashboardMarketItem"]["primary_source"];
export type MarketSession = components["schemas"]["DashboardMarketItem"]["session"];
export type DashboardPositionItem = components["schemas"]["DashboardPositionItem"];

/** 八个模块共有的四项；`data` 的具体形状由调用方给出。 */
export type ModuleEnvelope<T> = {
  status: DashboardStatus;
  as_of?: string | null;
  error?: string | null;
  data?: T | null;
};

/** 后端 `MODULE_NAMES` 的固定顺序，用于把降级列表写成中文。 */
const MODULE_TITLES: Record<string, string> = {
  market: "市场概况",
  account: "账户概览",
  risk: "风险监控",
  positions: "当前持仓",
  watchlist: "关注列表",
  alerts: "提醒",
  strategies: "策略运行",
  activity: "最近活动",
};

export type ModuleStatusView = {
  label: string;
  tone: string;
  ok: boolean;
};

const OK_TONE = "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
const STALE_TONE = "border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
const DOWN_TONE = "border-rose-600/40 bg-rose-500/10 text-rose-700 dark:text-rose-400";
const MUTED_TONE = "border-border text-muted-foreground";

export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return request<unknown>("/dashboard/summary").then((payload) => {
    const problem = dashboardProblem(payload);
    if (problem !== null) throw new Error(problem);
    return payload as DashboardSummary;
  });
}

/** 顶层结构缺失时整页显示不可用，不把残缺响应当成部分正常。 */
export function dashboardProblem(value: unknown): string | null {
  if (typeof value !== "object" || value === null) return "后端未返回首页汇总数据";
  const record = value as Record<string, unknown>;
  const required = [
    "market",
    "account",
    "risk",
    "positions",
    "watchlist",
    "alerts",
    "strategies",
    "activity",
  ];
  const missing = required.filter((key) => typeof record[key] !== "object" || record[key] === null);
  if (missing.length > 0) return `后端返回的首页汇总缺少模块：${missing.join("、")}`;
  return Array.isArray(record.degraded) ? null : "后端返回的首页汇总缺少 degraded 列表";
}

export function moduleStatusView(status: string): ModuleStatusView {
  if (status === "ok") return { label: "正常", tone: OK_TONE, ok: true };
  if (status === "stale") return { label: "陈旧", tone: STALE_TONE, ok: false };
  if (status === "unconfigured") return { label: "未配置", tone: MUTED_TONE, ok: false };
  if (status === "unavailable") return { label: "不可用", tone: DOWN_TONE, ok: false };
  return { label: "未知状态", tone: MUTED_TONE, ok: false };
}

/** 模块降级原因：优先用模块自己的 `error`，其次用顶层 `degraded` 的汇总。 */
export function degradedReason(
  summary: DashboardSummary,
  name: string,
  module: ModuleEnvelope<unknown>,
): string {
  const own = module.error?.trim();
  if (own) return own;
  const listed = summary.degraded.find((item) => item.module === name);
  return listed?.reason ?? "模块不可用";
}

/** 模块名与中文标题的对应；未知名称原样返回，不编造标题。 */
export function moduleTitle(name: string): string {
  return MODULE_TITLES[name] ?? name;
}

export function marketSessionLabel(session: MarketSession | string | null | undefined): string {
  if (session === "pre") return "盘前";
  if (session === "regular") return "正常交易";
  if (session === "post") return "盘后";
  if (session === "closed") return "休市";
  return `未知时段（${String(session)}）`;
}

export function dataSourceLabel(source: DashboardDataSource | string | null | undefined): string {
  if (source === "okx_spot") return "OKX 现货";
  if (source === "okx_swap") return "OKX 永续";
  if (source === "okx") return "OKX";
  if (source === "us_equity_proxy") return "美股代理行情";
  return `未知来源（${String(source)}）`;
}

export function exchangeStatusLabel(
  status: "ok" | "stale" | "unconfigured" | string | null | undefined,
): string {
  if (status === "ok") return "正常";
  if (status === "stale") return "陈旧";
  if (status === "unconfigured") return "未配置";
  return `未知状态（${String(status)}）`;
}

/** 契约里的比率（0.124 表示 12.4%）显示成百分比；回撤是正数幅度，不补正号。 */
export function ratioPercentText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return "未提供";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const percent = (number * 100).toFixed(2).replace(/\.?0+$/, "");
  return `${percent}%`;
}

export function signedRatioPercentText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return "未提供";
  const formatted = ratioPercentText(value);
  return formatted.startsWith("-") ? formatted : `+${formatted}`;
}

/** 后端已按百分数返回的字段（权重、覆盖率、保证金使用率）；这里只补单位。 */
export function percentText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return "未提供";
  return `${value}%`;
}

export function countText(value: number | null | undefined): string {
  return value === null || value === undefined ? "未提供" : String(value);
}

/** 交易所持仓的 `position_ref` 形如 `exchange:<account>:<pos_id>`，推送只带 `pos_id`。 */
export function exchangePosId(positionRef: string): string | null {
  const parts = positionRef.split(":");
  if (parts.length !== 3 || parts[0] !== "exchange" || parts[1] === "" || parts[2] === "") {
    return null;
  }
  return parts[2];
}

export type DashboardStreamInput = {
  quotes: Record<string, QuoteUpdate>;
  positions: Record<string, PositionUpdate>;
  account: AccountUpdate | null;
};

function laterOf(current: string | null | undefined, next: string | null): string | null {
  if (next === null) return current ?? null;
  if (current === null || current === undefined) return next;
  return next > current ? next : current;
}

/**
 * 把推送值合并到汇总上；只接受不早于模块时刻的更新，降级模块保持原样。
 * 没有任何变化时返回原对象，组件据此判断卡片里是否含推送值。
 */
export function withStreamUpdates(
  summary: DashboardSummary,
  input: DashboardStreamInput,
): DashboardSummary {
  let changed = false;

  let account = summary.account;
  const accountData = account.data;
  const accountUpdate = input.account;
  if (
    accountData != null &&
    accountUpdate !== null &&
    isAtLeast(updateTime(accountUpdate), accountData.captured_at ?? account.as_of ?? null)
  ) {
    const moment = updateTime(accountUpdate);
    account = {
      ...account,
      as_of: laterOf(account.as_of, moment),
      data: {
        ...accountData,
        account_id: accountUpdate.account_id || accountData.account_id,
        currency: accountUpdate.currency ?? accountData.currency,
        equity: accountUpdate.equity ?? accountData.equity,
        available_equity: accountUpdate.available_equity ?? accountData.available_equity,
        cash_balance: accountUpdate.cash_balance ?? accountData.cash_balance,
        unrealized_pnl: accountUpdate.unrealized_pnl ?? accountData.unrealized_pnl,
        used_margin: accountUpdate.used_margin ?? accountData.used_margin,
        available_margin: accountUpdate.available_margin ?? accountData.available_margin,
        margin_usage_pct: accountUpdate.margin_usage_pct ?? accountData.margin_usage_pct,
        captured_at: moment ?? accountData.captured_at,
        source: accountUpdate.source ?? accountData.source,
      },
    };
    changed = true;
  }

  let positions = summary.positions;
  const positionsData = positions.data;
  if (positionsData != null) {
    const reference = positions.as_of ?? null;
    let moduleTime = reference;
    const items = positionsData.items.map((item) => {
      const posId = item.source === "exchange" ? exchangePosId(item.position_ref) : null;
      const update = posId === null ? undefined : input.positions[posId];
      if (update === undefined || !isAtLeast(updateTime(update), reference)) return item;
      const markPrice = update.mark_px ?? item.mark_price;
      const unrealizedPnl = update.upl ?? item.unrealized_pnl;
      if (markPrice === item.mark_price && unrealizedPnl === item.unrealized_pnl) return item;
      moduleTime = laterOf(moduleTime, updateTime(update));
      return { ...item, mark_price: markPrice, unrealized_pnl: unrealizedPnl };
    });
    if (items.some((item, index) => item !== positionsData.items[index])) {
      positions = { ...positions, as_of: moduleTime, data: { ...positionsData, items } };
      changed = true;
    }
  }

  let watchlist = summary.watchlist;
  const watchlistData = watchlist.data;
  if (watchlistData != null) {
    const reference = watchlist.as_of ?? null;
    let moduleTime = reference;
    const items = watchlistData.items.map((item) => {
      const quote = input.quotes[item.inst_id];
      if (quote === undefined || quote.last === null) return item;
      if (!isAtLeast(quote.as_of ?? quote.received_at, reference)) return item;
      if (quote.last === item.last_price) return item;
      moduleTime = laterOf(moduleTime, quote.as_of ?? quote.received_at);
      return { ...item, last_price: quote.last };
    });
    if (items.some((item, index) => item !== watchlistData.items[index])) {
      watchlist = { ...watchlist, as_of: moduleTime, data: { ...watchlistData, items } };
      changed = true;
    }
  }

  return changed ? { ...summary, account, positions, watchlist } : summary;
}

/** 模块时间：没有时刻时如实写「无数据时间」，不借用页面加载时间。 */
export function asOfText(value: string | null | undefined): string {
  return value === null || value === undefined || value.trim() === ""
    ? "无数据时间"
    : formatBeijingTime(value);
}

/** 只用于进度条宽度：把后端已给的百分数夹到 0 至 100，不参与任何业务计算。 */
export function clampedPercent(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.min(Math.max(number, 0), 100);
}

/** 金额字段展示：有值补币种，没有就写未提供，不补 0。 */
export function amountText(
  value: string | null | undefined,
  currency: string | null | undefined,
): string {
  if (value === null || value === undefined || value.trim() === "") return "未提供";
  if (currency === null || currency === undefined || currency.trim() === "") {
    return `${value}（后端未返回币种）`;
  }
  return `${value} ${currency}`;
}
