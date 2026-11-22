import { asOfText } from "../../lib/dashboard";
import type { MacroReading } from "../../lib/api";
import { granularityLabel, readingValueText, regimeLabel, regimeTone } from "../../lib/macro";
import { cn } from "../../lib/utils";

/**
 * 关注列表的「市场风险」块：只有全局风险读数（VIX）的值、分级与更新时间。
 *
 * 数据来自 `GET /api/macro/overview`，由页面挑出 VIX 那一条传进来；这里不判断该展示
 * 哪些序列，也不做任何换算。
 */
export function MarketRiskBlock({
  reading,
  loading,
  error,
}: {
  reading: MacroReading | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && reading === null) {
    return <p className="text-[11px] text-muted-foreground">读取中…</p>;
  }
  if (error !== null) {
    return <p className="text-[11px] text-destructive">{error}</p>;
  }
  return (
    <div data-market-risk="vix" data-regime={reading?.regime ?? "none"}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-mono text-base font-semibold tabular-nums">
          {readingValueText(reading) ?? "缺失"}
        </p>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium",
            regimeTone(reading?.regime),
          )}
        >
          {regimeLabel(reading?.regime)}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        更新时间：{asOfText(reading?.as_of)}
        {reading === null ? "" : ` · ${granularityLabel(reading.granularity)}`}
        {reading?.is_delayed ? " · 延迟" : ""}
      </p>
    </div>
  );
}
