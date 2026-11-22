import { asOfText } from "../../lib/dashboard";
import { signedTone } from "../../lib/display";
import {
  changeText,
  delayLabel,
  granularityLabel,
  macroQualityLabel,
  macroStaleNotice,
  primaryReading,
  readingValueText,
  regimeLabel,
  regimeTone,
  spreadTone,
  spreadUnavailableText,
  spreadValueText,
  vixReading,
} from "../../lib/macro";
import type { MacroOverviewResponse, MacroReading, MacroSpread } from "../../lib/api";
import { cn } from "../../lib/utils";

/**
 * 首页「市场概况」卡里的宏观三行：10Y、2Y→10Y 利差、VIX。
 *
 * 数值、`as_of`、来源、是否延迟、利差是否倒挂、VIX 分级全部来自
 * `GET /api/macro/overview`；这里只排版，不合并分钟级与日结值的时间。
 */

const POSITIVE_BADGE =
  "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
const WARN_BADGE = "border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
const NEUTRAL_BADGE = "border-border bg-muted/40 text-muted-foreground";

function RowBadge({ tone, children }: { tone: string; children: string }) {
  return (
    <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium", tone)}>
      {children}
    </span>
  );
}

/** 一行宏观读数：国债与 VIX 共用，差别只在右侧徽标（VIX 展示分级，其余展示质量与延迟）。 */
function MacroFact({
  label,
  reading,
  showRegime = false,
}: {
  label: string;
  reading: MacroReading | null;
  showRegime?: boolean;
}) {
  const value = readingValueText(reading);
  const change = changeText(reading);
  const delayed = delayLabel(reading);
  return (
    <div
      data-macro-series={reading?.series_id ?? "unknown"}
      data-regime={showRegime ? (reading?.regime ?? "none") : undefined}
      className="rounded-md border px-3 py-2"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{label}</p>
          <p className="break-words text-[11px] text-muted-foreground">
            {reading === null
              ? "后端未返回这一项"
              : `${granularityLabel(reading.granularity)} · ${reading.provider}`}
          </p>
        </div>
        {reading === null ? null : showRegime ? (
          <RowBadge tone={regimeTone(reading.regime)}>{regimeLabel(reading.regime)}</RowBadge>
        ) : (
          <span className="flex shrink-0 gap-1">
            <RowBadge
              tone={reading.quality_status === "normal" ? POSITIVE_BADGE : WARN_BADGE}
            >
              {macroQualityLabel(reading.quality_status)}
            </RowBadge>
            {delayed === null ? null : <RowBadge tone={NEUTRAL_BADGE}>{delayed}</RowBadge>}
          </span>
        )}
      </div>
      <p className="mt-2 break-words font-mono text-xl font-semibold tabular-nums">
        {value ?? "缺失"}
      </p>
      {change === null ? null : (
        <p className={cn("font-mono text-xs tabular-nums", signedTone(change))}>日变化 {change}</p>
      )}
      {reading?.error ? (
        <p className="mt-1 break-words text-[11px] text-muted-foreground">{reading.error}</p>
      ) : null}
      <p className="mt-2 text-[11px] text-muted-foreground">
        数据时间：{asOfText(reading?.as_of)}
      </p>
      <p className="mt-1 break-words text-[11px] text-muted-foreground">
        来源：
        {reading?.source_url ? (
          <a
            href={reading.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            {reading.provider}
          </a>
        ) : (
          (reading?.provider ?? "后端未返回来源")
        )}
      </p>
    </div>
  );
}

function SpreadFact({ spread }: { spread: MacroSpread | null }) {
  const value = spreadValueText(spread);
  const reason = spreadUnavailableText(spread);
  const sources = spread?.sources ?? [];
  return (
    <div data-macro-series="spread" className="rounded-md border px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">2Y→10Y 利差</p>
          <p className="text-[11px] text-muted-foreground">同一结算日的 2Y 与 10Y</p>
        </div>
        {spread?.inverted ? <RowBadge tone={regimeTone("panic")}>倒挂</RowBadge> : null}
      </div>
      <p
        className={cn(
          "mt-2 break-words font-mono text-xl font-semibold tabular-nums",
          spreadTone(spread),
        )}
      >
        {value ?? "不可用"}
      </p>
      {reason === null ? null : (
        <p className="mt-1 break-words text-[11px] text-muted-foreground">{reason}</p>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">
        结算日：{spread?.trading_day ?? "无数据"}
      </p>
      <p className="mt-1 break-words text-[11px] text-muted-foreground">
        来源：
        {sources.length === 0
          ? "后端未返回来源"
          : sources.map((source, index) => (
              <span key={`${source.provider}:${index}`}>
                {index > 0 ? "、" : null}
                {source.source_url ? (
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {source.provider}
                  </a>
                ) : (
                  source.provider
                )}
              </span>
            ))}
      </p>
    </div>
  );
}

export function MacroRows({
  overview,
  error,
  loading,
}: {
  overview: MacroOverviewResponse | null;
  error: string | null;
  loading: boolean;
}) {
  if (loading && overview === null) {
    return <p className="text-sm text-muted-foreground">正在读取宏观数据…</p>;
  }
  if (error !== null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (overview === null) {
    return <p className="text-sm text-muted-foreground">宏观数据不可用。</p>;
  }
  const notice = macroStaleNotice(overview);
  const vix = vixReading(overview);
  return (
    <section aria-label="宏观数据" className="space-y-2">
      {notice === null ? null : (
        <p
          role="status"
          className="rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
        >
          {notice}
        </p>
      )}
      <MacroFact label="美国 10 年期国债" reading={primaryReading(overview, "us10y")} />
      <SpreadFact spread={overview.spread} />
      <MacroFact label={vix?.name ?? "恐慌指数 VIX"} reading={vix} showRegime />
    </section>
  );
}
