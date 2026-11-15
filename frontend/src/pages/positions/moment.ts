import { formatBeijingTime } from "../../lib/display";
import { MISSING_VALUE } from "../../lib/positions";

/** 时间缺失时统一显示「未提供」，不拿其他时刻代替。 */
export function momentText(value: string | null | undefined): string {
  return value === null || value === undefined || value.trim() === ""
    ? MISSING_VALUE
    : formatBeijingTime(value);
}
