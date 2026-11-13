/**
 * 展示层格式化。
 *
 * 契约里的数值都是十进制字符串，页面**原样呈现**，这里只补正负号与配色，
 * 不对数值做业务派生。收益率按百分比显示属于展示单位的换算：契约里 0.05 表示 5%，
 * 页面显示 +5%，数值本身仍由后端计算。
 */

import type { components } from "../api/types";

export type InstType = components["schemas"]["InstrumentInfo"]["inst_type"];
export type AssetType = components["schemas"]["InstrumentInfo"]["asset_type"];
export type SignalAction = components["schemas"]["Signal"]["action"];

const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  tokenized_equity: "代币化股票",
  crypto: "加密资产",
  commodity_token: "代币化商品",
  unknown: "未知资产类型",
};

export function assetTypeLabel(assetType: AssetType): string {
  return ASSET_TYPE_LABELS[assetType];
}

/** 契约用 SPOT / SWAP，页面对用户展示 SPOT / PERP。 */
export function instTypeLabel(instType: InstType): "SPOT" | "PERP" {
  return instType === "SWAP" ? "PERP" : "SPOT";
}

/** 按数值正负补 `+`，负号沿用契约原值。 */
export function signedValue(value: string): string {
  return value.trim().startsWith("-") ? value : `+${value}`;
}

/** 涨跌额按价格自身的小数位数显示，避免低价标的被四舍五入成 +0.00。 */
export function priceChangeValue(change: string, price: string | null | undefined): string {
  const number = Number(change);
  if (!Number.isFinite(number)) return change;
  const decimalsOf = (value: string | null | undefined) =>
    value?.includes(".") ? value.split(".")[1].length : 0;
  const places = Math.min(Math.max(decimalsOf(price), 2), 8);
  const [whole, fraction = ""] = number.toFixed(places).split(".");
  const trimmed = fraction.replace(/0+$/, "").padEnd(2, "0");
  return signedValue(`${whole}.${trimmed}`);
}

export function signedTone(value: string): string {
  const trimmed = value.trim();
  if (trimmed.startsWith("-")) return "text-rose-600 dark:text-rose-400";
  if (Number(trimmed) === 0) return "text-muted-foreground";
  return "text-emerald-600 dark:text-emerald-400";
}

/** 把契约里的比率（0.05 表示 5%）显示成百分比，并补上正号。 */
export function percentValue(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const percent = (number * 100).toFixed(2).replace(/\.?0+$/, "");
  return percent.startsWith("-") ? `${percent}%` : `+${percent}%`;
}

export function signalTone(action: SignalAction): string {
  if (action === "BUY") return "border-emerald-600/40 text-emerald-600 dark:text-emerald-400";
  if (action === "SELL") return "border-rose-600/40 text-rose-600 dark:text-rose-400";
  return "text-muted-foreground";
}

/** 后端时间戳是 UTC；界面统一按北京时间显示。 */
export function formatBeijingTime(iso: string, withTime = true): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).formatToParts(date);
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  const day = `${pick("year")}-${pick("month")}-${pick("day")}`;
  return withTime ? `${day} ${pick("hour")}:${pick("minute")}` : day;
}
