/** 研究页展示用的格式化：只做呈现，不参与任何计算。 */

export function formatDecimal(value: string | null | undefined, digits = 4): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

export function formatRatioPercent(value: string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : "—";
}

export function formatMomentum(value: string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "—";
  }
  const sign = parsed > 0 ? "+" : "";
  return `${sign}${(parsed * 100).toFixed(digits)}%`;
}

export function formatPValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "—";
  }
  return parsed < 0.001 && parsed > 0 ? parsed.toExponential(2) : parsed.toFixed(3);
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

/** `best_lag` 语义：正数表示对手方领先目标，负数是目标领先对手方。 */
export function lagLabel(lag: number | null | undefined): string {
  if (lag === null || lag === undefined) {
    return "—";
  }
  if (lag === 0) {
    return "同步";
  }
  return lag > 0 ? `对手方领先 ${lag} 根` : `目标领先 ${-lag} 根`;
}

export function trendLabel(trend: string | null | undefined): string {
  if (trend === "rising") {
    return "走强";
  }
  if (trend === "falling") {
    return "走弱";
  }
  if (trend === "flat") {
    return "持平";
  }
  return "—";
}
