import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { asOfText, marketSessionLabel } from "../../lib/dashboard";
import { signedTone, signedValue } from "../../lib/display";
import {
  marketItemStatusLabel,
  overviewStaleNotice,
  pointsWithSources,
  summarySourceHref,
  summarySourceLabel,
  type AiSummary,
  type AiSummaryPoint,
  type AiSummarySource,
  type MarketOverviewItem,
  type MarketSnapshot,
} from "../../lib/market";
import type { MacroOverviewResponse } from "../../lib/api";
import { cn } from "../../lib/utils";
import { MacroRows } from "./macro-rows";
import { StatusBadge } from "./module-card";

const ITEM_OK_TONE =
  "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
const ITEM_WARN_TONE =
  "border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
const ITEM_DOWN_TONE =
  "border-rose-600/40 bg-rose-500/10 text-rose-700 dark:text-rose-400";

function itemStatusTone(item: MarketOverviewItem): string {
  if (item.quality_status === "missing" || item.quality_status === "abnormal") {
    return ITEM_DOWN_TONE;
  }
  if (item.quality_status === "normal" && !item.is_delayed) return ITEM_OK_TONE;
  return ITEM_WARN_TONE;
}

function loadingBadge() {
  return (
    <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      读取中
    </span>
  );
}

function cardStatus(
  data: unknown,
  error: string | null,
  loading: boolean,
  stale: boolean,
): string {
  if (loading) return "loading";
  if (error !== null || data === null) return "unavailable";
  return stale ? "stale" : "ok";
}

function Status({ status }: { status: string }) {
  if (status === "loading") return loadingBadge();
  return <StatusBadge status={status} />;
}

function itemChangeText(item: MarketOverviewItem): string {
  if (item.change === null && item.change_pct === null) return "涨跌未提供";
  const amount = item.change === null ? "涨跌额未提供" : signedValue(item.change);
  const percent = item.change_pct === null ? "" : `（${signedValue(item.change_pct)}%）`;
  return `${amount}${percent}`;
}

/** 一个市场指标：数值、涨跌、时段、来源、时间与延迟状态全部来自接口。 */
export function MarketItemBody({ item }: { item: MarketOverviewItem }) {
  return (
    <div data-market-symbol={item.symbol} className="rounded-md border px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{item.symbol}</p>
          <p className="break-words text-[11px] text-muted-foreground">{item.name}</p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium",
            itemStatusTone(item),
          )}
        >
          {marketItemStatusLabel(item)}
        </span>
      </div>
      <p className="mt-2 break-words font-mono text-xl font-semibold tabular-nums">
        {item.value ?? "缺失"}
      </p>
      <p
        className={cn(
          "font-mono text-xs tabular-nums",
          item.change_pct === null ? "text-muted-foreground" : signedTone(item.change_pct),
        )}
      >
        {itemChangeText(item)}
      </p>
      <p className="mt-2 text-[11px] text-muted-foreground">
        市场时段：{marketSessionLabel(item.market_session)}
      </p>
      <p className="mt-1 break-words text-[11px] text-muted-foreground">
        来源：
        {item.source_url ? (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            {item.source}
          </a>
        ) : (
          item.source
        )}
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground">
        报价时间：{asOfText(item.as_of)}
      </p>
    </div>
  );
}

/** 首页市场概况：BTC 一项与顶层过期提示。 */
export function MarketOverviewBody({
  overview,
  error,
  loading,
}: {
  overview: MarketSnapshot | null;
  error: string | null;
  loading: boolean;
}) {
  if (loading && overview === null) {
    return <p className="text-sm text-muted-foreground">正在读取市场概况…</p>;
  }
  if (error !== null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (overview === null) {
    return <p className="text-sm text-muted-foreground">市场概况不可用。</p>;
  }
  const notice = overviewStaleNotice(overview);
  return (
    <div className="space-y-3">
      {notice ? (
        <p
          role="status"
          className="rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
        >
          {notice}
        </p>
      ) : null}
      {overview.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">后端没有返回市场指标。</p>
      ) : (
        <dl className="grid gap-3">
          {overview.items.map((item) => (
            <MarketItemBody key={item.symbol} item={item} />
          ))}
        </dl>
      )}
    </div>
  );
}

export function MarketOverviewCard({
  overview,
  error,
  loading,
  macro,
  macroError,
  macroLoading,
}: {
  overview: MarketSnapshot | null;
  error: string | null;
  loading: boolean;
  macro: MacroOverviewResponse | null;
  macroError: string | null;
  macroLoading: boolean;
}) {
  const status = cardStatus(overview, error, loading, overview?.stale ?? false);
  return (
    <Card
      id="market-overview"
      className="min-w-0 scroll-mt-14"
      data-module="market"
      data-status={status}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle>市场概况</CardTitle>
          <Status status={status} />
        </div>
        <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>数据时间：{asOfText(overview?.as_of)}</span>
          <span aria-hidden="true">·</span>
          <span>来源：逐行标注</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <MarketOverviewBody overview={overview} error={error} loading={loading} />
        <section className="space-y-2 border-t pt-3">
          <h4 className="text-xs font-medium text-muted-foreground">全球宏观</h4>
          <MacroRows overview={macro} error={macroError} loading={macroLoading} />
        </section>
      </CardContent>
    </Card>
  );
}

function SourceLink({ source }: { source: AiSummarySource }) {
  const href = summarySourceHref(source);
  const label = `${summarySourceLabel(source.type)} · ${source.id}`;
  const className = "text-primary underline-offset-4 hover:underline";
  if (href === null) {
    return <span className="text-muted-foreground">{label}</span>;
  }
  if (href.startsWith("#")) {
    return (
      <a href={href} className={className}>
        {label}
      </a>
    );
  }
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {label}
    </a>
  );
}

function PointList({ points }: { points: AiSummaryPoint[] }) {
  return (
    <ul className="space-y-3">
      {points.map((point, index) => (
        <li key={`${index}:${point.text}`} className="border-b border-border/60 pb-2 last:border-0">
          <p className="text-sm">{point.text}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
            <span className="text-muted-foreground">来源：</span>
            {point.sources.map((source, sourceIndex) => (
              <SourceLink key={`${source.type}:${source.id}:${sourceIndex}`} source={source} />
            ))}
          </p>
        </li>
      ))}
    </ul>
  );
}

/** 首页市场摘要：只展示接口给出的结论、事实点、风险、来源和生成时间。 */
export function MarketSummaryCard({
  summary,
  dataAsOf,
  error,
  loading,
}: {
  summary: AiSummary | null;
  dataAsOf: string | null;
  error: string | null;
  loading: boolean;
}) {
  const status = cardStatus(summary, error, loading, summary?.stale ?? false);
  const points = summary === null ? [] : pointsWithSources(summary.points);
  const risks = summary === null ? [] : pointsWithSources(summary.risks);
  const notice =
    summary === null
      ? null
      : overviewStaleNotice({ stale: summary.stale, stale_reason: summary.stale_notice });
  return (
    <Card
      id="market-summary"
      className="min-w-0 scroll-mt-14"
      data-module="market_summary"
      data-status={status}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle>市场摘要</CardTitle>
          <Status status={status} />
        </div>
        <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>生成时间：{asOfText(summary?.generated_at)}</span>
          <span aria-hidden="true">·</span>
          <span>数据截止：{asOfText(dataAsOf)}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && summary === null ? (
          <p className="text-sm text-muted-foreground">正在生成市场摘要…</p>
        ) : error !== null ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : summary === null ? (
          <p className="text-sm text-muted-foreground">市场摘要不可用。</p>
        ) : (
          <>
            {notice ? (
              <p
                role="status"
                className="rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
              >
                {notice}
              </p>
            ) : null}
            <p className="text-base font-medium">{summary.overall}</p>
            <section aria-label="观察要点">
              <h4 className="text-xs font-medium text-muted-foreground">观察要点</h4>
              {points.length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">没有带来源的观察要点。</p>
              ) : (
                <div className="mt-2">
                  <PointList points={points} />
                </div>
              )}
            </section>
            {risks.length > 0 ? (
              <section aria-label="风险提示">
                <h4 className="text-xs font-medium text-muted-foreground">风险提示</h4>
                <div className="mt-2">
                  <PointList points={risks} />
                </div>
              </section>
            ) : null}
            {summary.disclaimer ? (
              <p
                data-summary-disclaimer
                className="border-t pt-2 text-[11px] leading-5 text-muted-foreground"
              >
                {summary.disclaimer}
              </p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
