/**
 * 持仓页的只读客户端与展示文案。
 *
 * 账户与交易所持仓的数值全部来自后端快照；这里不计算盈亏、名义价值、
 * 保证金比例或今日盈亏，只把契约里的字符串原样交给页面。
 */

import type { components } from "../api/types";
import { request } from "./api";
import { percentValue, signedValue } from "./display";

export type AccountSummary = components["schemas"]["AccountSummaryResponse"];
export type AccountSync = components["schemas"]["AccountSyncResponse"];
export type ExchangePositions = components["schemas"]["ExchangePositionsResponse"];
export type ExchangePosition = ExchangePositions["items"][number];
export type AccountStatus = AccountSummary["status"];

export const MISSING_VALUE = "未提供";

export function fetchAccountSummary(): Promise<AccountSummary> {
  return request<AccountSummary>("/account/summary");
}

/** 只触发 OKX 只读快照同步，不产生任何订单。 */
export function syncAccount(): Promise<AccountSync> {
  return request<AccountSync>("/account/sync", { method: "POST" });
}

export function fetchExchangePositions(): Promise<ExchangePositions> {
  return request<ExchangePositions>("/positions/exchange");
}

export function valueOrMissing(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return value;
}

/** 账户来源用文字区分 REST 快照与 WebSocket 推送，避免混成同一个来源。 */
export function accountSourceLabel(source: string | null | undefined): string {
  if (source === null || source === undefined || source.trim() === "") return MISSING_VALUE;
  if (source === "okx_rest") return "OKX REST 快照";
  if (source === "okx_ws") return "OKX WebSocket 推送";
  return source;
}

export function accountStatusLabel(status: AccountStatus): string {
  if (status === "unconfigured") return "未配置 OKX 密钥";
  if (status === "stale") return "快照已过期";
  return "正常";
}

export function positionSideLabel(side: ExchangePosition["pos_side"]): string {
  return side === "short" ? "空" : "多";
}

export function marginModeLabel(mode: string | null | undefined): string {
  if (mode === null || mode === undefined || mode.trim() === "") return MISSING_VALUE;
  if (mode === "cross") return "全仓";
  if (mode === "isolated") return "逐仓";
  return mode;
}

/** 后端已经按百分数返回，这里只补单位，不再乘以 100。 */
export function marginUsageText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return `${value}%`;
}

/** 契约里的 `upl_ratio` 是比率（0.0204 表示 2.04%），展示层只做单位换算。 */
export function uplRatioText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return percentValue(value);
}

/** 盈亏类字段按契约原值展示，只补正负号。 */
export function pnlText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return signedValue(value);
}
