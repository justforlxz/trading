/** 驾驶舱的展示格式化与证据取值：只做呈现，不参与任何指标计算。 */

import type { OpportunityDirection, OpportunityKind } from "../../lib/api";

export const kindLabels: Record<OpportunityKind, string> = {
  directional: "方向性",
  relative_value: "相对价值",
};

export const directionLabels: Record<OpportunityDirection, string> = {
  long: "做多",
  short: "做空",
  pair: "配对",
};

export const sessionLabels: Record<string, string> = {
  PRE: "盘前",
  REGULAR: "盘中",
  POST: "盘后",
  CLOSED: "休市",
};

export function evidenceNumber(
  evidence: Record<string, unknown>,
  key: string,
): number | null {
  const value = evidence[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function evidenceString(
  evidence: Record<string, unknown>,
  key: string,
): string | null {
  const value = evidence[key];
  return typeof value === "string" ? value : null;
}

/** 比率（0.12）→ 带符号百分比（+12.00%）。 */
export function formatSignedPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

export function formatPlainPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

export function formatScore(value: string | null | undefined, digits = 4): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined || !Number.isFinite(milliseconds)) {
    return "—";
  }
  if (milliseconds < 1000) {
    return `${Math.round(milliseconds)} 毫秒`;
  }
  return `${(milliseconds / 1000).toFixed(1)} 秒`;
}
