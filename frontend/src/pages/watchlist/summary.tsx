import { MarketRiskBlock } from "../../components/ui/market-risk";
import type { MacroReading } from "../../lib/api";
import { cn } from "../../lib/utils";
import {
  averageChangeText,
  averageChangeTone,
  CHANGE_BUCKETS,
  CHANGE_BUCKET_COLORS,
  CHANGE_BUCKET_LABELS,
  toneClass,
  type PendingDigest,
  type WatchlistAggregate,
} from "../../lib/watchlist-summary";

/**
 * 关注汇总：关注规模、涨跌分布、市场风险与需要处理。
 *
 * 分类筛选是联动的：入参是当前分类筛选后的标的列表，三块汇总跟着一起收窄。
 * 输入全部来自 `aggregateWatchlist` / `buildPendingDigest`，这里不重新算数，
 * 也不在缺数据时补 0。移动端由 `.wl-grid[data-view]` 决定这一栏显示还是隐藏。
 */
export function WatchlistSummary({
  aggregate,
  pending,
  marketRisk,
  marketRiskLoading = false,
  marketRiskError = null,
}: {
  aggregate: WatchlistAggregate;
  pending: PendingDigest;
  marketRisk: MacroReading | null;
  marketRiskLoading?: boolean;
  marketRiskError?: string | null;
}) {
  const segments = CHANGE_BUCKETS.filter((bucket) => aggregate.distribution[bucket] > 0);

  return (
    <aside className="wl-summary rounded-lg border bg-card text-card-foreground shadow-sm">
      <header className="flex items-baseline justify-between gap-2 border-b px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">关注汇总</h2>
        <span className="text-[11px] text-muted-foreground">24H</span>
      </header>

      <section className="border-b px-4 py-3 last:border-b-0">
        <h3 className="text-[11px] font-medium text-muted-foreground">关注规模</h3>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <div className="rounded-md border px-2 py-1.5">
            <p className="text-[11px] text-muted-foreground">有信号</p>
            <p className="mt-0.5 font-mono text-base font-semibold tabular-nums">
              {aggregate.signalCount}
            </p>
          </div>
          <div className="rounded-md border px-2 py-1.5">
            <p className="text-[11px] text-muted-foreground">平均涨跌</p>
            <p
              className={cn(
                "mt-0.5 font-mono text-base font-semibold tabular-nums",
                averageChangeTone(aggregate.averageChangePct),
              )}
            >
              {averageChangeText(aggregate.averageChangePct)}
            </p>
          </div>
        </div>
      </section>

      <section className="border-b px-4 py-3 last:border-b-0">
        <h3 className="text-[11px] font-medium text-muted-foreground">涨跌分布</h3>
        <div className="mt-2">
          <div
            className="flex overflow-hidden rounded-full"
            style={{ height: 8, gap: 2 }}
            role="img"
            aria-label={`涨跌分布：${CHANGE_BUCKETS.map(
              (bucket) => `${CHANGE_BUCKET_LABELS[bucket]} ${aggregate.distribution[bucket]}`,
            ).join(" / ")}`}
          >
            {segments.map((bucket) => (
              <span
                key={bucket}
                className="block h-full"
                style={{
                  flex: `${aggregate.distribution[bucket]} 1 0`,
                  background: CHANGE_BUCKET_COLORS[bucket],
                }}
              />
            ))}
          </div>
          <div
            className="mt-2 text-[11px]"
            style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}
          >
            <span className="text-emerald-600 dark:text-emerald-400">
              {CHANGE_BUCKET_LABELS.up} {aggregate.distribution.up}
            </span>
            <span className="text-destructive">
              {CHANGE_BUCKET_LABELS.down} {aggregate.distribution.down}
            </span>
            <span className="text-muted-foreground">
              {CHANGE_BUCKET_LABELS.flat} {aggregate.distribution.flat}
            </span>
          </div>
        </div>
      </section>

      <section className="border-b px-4 py-3 last:border-b-0">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-[11px] font-medium text-muted-foreground">市场风险</h3>
          <span className="text-[11px] text-muted-foreground">全局</span>
        </div>
        <div className="mt-2">
          <MarketRiskBlock
            reading={marketRisk}
            loading={marketRiskLoading}
            error={marketRiskError}
          />
        </div>
      </section>

      <section className="border-b px-4 py-3 last:border-b-0">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-[11px] font-medium text-muted-foreground">需要处理</h3>
          <span className="text-[11px] text-muted-foreground">{pending.total} 项</span>
        </div>
        <div className="mt-2">
          {pending.entries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">暂无待处理项</p>
          ) : (
            <div className="flex flex-col">
              {pending.entries.map((entry) => (
                <div
                  key={entry.key}
                  className="flex items-center justify-between gap-2 border-b py-1.5 last:border-b-0"
                >
                  <span className="min-w-0 truncate text-xs">{entry.label}</span>
                  <span className={cn("shrink-0 text-[11px]", toneClass(entry.tone))}>
                    {entry.detail}
                  </span>
                </div>
              ))}
            </div>
          )}
          {pending.overflow > 0 ? (
            <p className="mt-2 text-[11px] text-muted-foreground">另有 {pending.overflow} 项</p>
          ) : null}
        </div>
      </section>
    </aside>
  );
}
