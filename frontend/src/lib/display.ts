/**
 * 展示层格式化。
 *
 * 契约里的数值都是十进制字符串，页面**原样呈现**，这里只补正负号与配色，
 * 不对数值做任何换算或业务派生。
 */

import type { components } from "../api/types";

export type InstType = components["schemas"]["InstrumentInfo"]["inst_type"];
export type SignalAction = components["schemas"]["Signal"]["action"];

/** 契约用 SPOT / SWAP，页面对用户展示 SPOT / PERP。 */
export function instTypeLabel(instType: InstType): "SPOT" | "PERP" {
  return instType === "SWAP" ? "PERP" : "SPOT";
}

/** 按数值正负补 `+`，负号沿用契约原值。 */
export function signedValue(value: string): string {
  return value.trim().startsWith("-") ? value : `+${value}`;
}

export function signedTone(value: string): string {
  const trimmed = value.trim();
  if (trimmed.startsWith("-")) return "text-rose-600 dark:text-rose-400";
  if (Number(trimmed) === 0) return "text-muted-foreground";
  return "text-emerald-600 dark:text-emerald-400";
}

export function signalTone(action: SignalAction): string {
  if (action === "BUY") return "border-emerald-600/40 text-emerald-600 dark:text-emerald-400";
  if (action === "SELL") return "border-rose-600/40 text-rose-600 dark:text-rose-400";
  return "text-muted-foreground";
}
