/**
 * 回测结果页的展示辅助：只做字符串裁剪与标签映射，不参与任何业务计算。
 */

/** UTC 时刻 → 表格里好读的短格式；只裁字符串，不改时区。 */
export function formatMoment(iso: string): string {
  return `${iso.slice(0, 16).replace("T", " ")} UTC`;
}

export function directionLabel(side: "long" | "short"): "多" | "空" {
  return side === "long" ? "多" : "空";
}

export function directionTone(side: "long" | "short"): string {
  return side === "long"
    ? "border-emerald-600/40 text-emerald-600 dark:text-emerald-400"
    : "border-rose-600/40 text-rose-600 dark:text-rose-400";
}

/** 一次运行使用的策略参数 → 列表与详情里好读的一行；按键名排序，空参数明确写「默认参数」。 */
export function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params).sort(([left], [right]) => left.localeCompare(right));
  if (entries.length === 0) return "默认参数";
  return entries.map(([key, value]) => `${key}=${String(value)}`).join(" · ");
}
