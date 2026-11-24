/**
 * 首页：一屏判断今天要不要动手。
 *
 * 排版按「结论 → 钱 → 标的 → 环境 → 待办 → 系统」排，不是八张等权卡片：
 * 结论条通栏，下面三行两列（5/7、7/5、7/5）。窄屏单列。
 *
 * 数值全部来自 `GET /api/dashboard/summary` 等接口，页面不重算盈亏、风险等级
 * 或覆盖率；结论条只把后端字段拼成一句话，字段缺失时整项省略。
 */

import { Pencil, RefreshCw } from "lucide-react";
import { useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import { StreamNotice } from "../../components/ui/stream-status";
import type { MacroOverviewResponse } from "../../lib/api";
import type { AlertStatusUpdate } from "../../lib/alerts";
import {
  asOfText,
  exchangeStatusLabel,
  moduleTitle,
  type DashboardPushed,
  type DashboardSummary,
} from "../../lib/dashboard";
import {
  changeText,
  macroStaleNotice,
  primaryReading,
  readingValueText,
  regimeLabel,
  regimeTone,
  spreadTone,
  spreadUnavailableText,
  spreadValueText,
} from "../../lib/macro";
import type { AiSummary, MarketSnapshot } from "../../lib/market";
import { overviewStaleNotice } from "../../lib/market";
import { pinnedCardRows, pinnedCountText, type PinnedCandidate } from "../../lib/home-pinned";
import { riskLevelView } from "../../lib/risk";
import type { StreamLiveness } from "../../lib/stream";
import { cn } from "../../lib/utils";
import { WatchlistPicker } from "./watchlist-picker";

export type HomeViewProps = {
  summary: DashboardSummary | null;
  error: string | null;
  loading: boolean;
  priceLiveness: StreamLiveness;
  accountLiveness: StreamLiveness;
  pushed: DashboardPushed;
  marketOverview: MarketSnapshot | null;
  marketOverviewError: string | null;
  marketOverviewLoading: boolean;
  macroOverview: MacroOverviewResponse | null;
  macroOverviewError: string | null;
  macroOverviewLoading: boolean;
  aiSummary: AiSummary | null;
  aiSummaryError: string | null;
  aiSummaryLoading: boolean;
  onRefresh: () => void;
  onResolveAlert?: (alertId: string, status: AlertStatusUpdate) => void;
  resolvingAlertId?: string | null;
  /** 首页关注列表置顶的标的（服务端 `display.homepage_pinned`），按选择顺序。 */
  pinnedWatchlist: string[];
  /** 整份自选（`GET /api/watchlist`）：弹窗的候选，不受首页汇总五行上限的影响。 */
  watchlistCandidates: PinnedCandidate[];
  /** 保存置顶清单；失败时抛错，由弹窗自己显示原因并保持打开。 */
  onSavePinned: (next: string[]) => Promise<void>;
};

/** 后端返回的数值字段是字符串；缺失、空串与非数字一律当成「没有这个值」。 */
function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: string | null | undefined): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return parsed.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function signed(value: string | null | undefined): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(2)}`;
}

function pct(value: string | null | undefined): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(2)}%`;
}

function tone(value: string | null | undefined): string {
  const parsed = num(value);
  if (parsed === null || parsed === 0) return "text-muted-foreground";
  return parsed > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

function trendText(value: string | null | undefined): string {
  if (value === "bullish") return "偏多";
  if (value === "bearish") return "偏空";
  if (value === "neutral") return "中性";
  return "—";
}

/** 风险计数徽标的告警配色；数值缺失时不用这两组色，退回中性配色。 */
const ALERT_BADGE = "border-rose-600/40 bg-rose-500/5 text-rose-700 dark:text-rose-400";
const WARN_BADGE = "border-amber-600/40 bg-amber-500/5 text-amber-700 dark:text-amber-400";

/** 首页区块外壳：比 `Card` 更紧凑（一屏装下六块），标题行右侧留一个说明位。 */
function Panel({
  block,
  title,
  hint,
  className,
  children,
}: {
  block: string;
  title: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      id={block}
      data-block={block}
      className={cn(
        "min-w-0 scroll-mt-14 rounded-lg border bg-card text-card-foreground shadow-sm",
        className,
      )}
    >
      <header className="flex items-baseline justify-between gap-3 px-4 pt-3">
        <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
        {hint ? (
          <span className="truncate text-[11px] text-muted-foreground">{hint}</span>
        ) : null}
      </header>
      <div className="px-4 pb-4 pt-2">{children}</div>
    </section>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex items-baseline justify-between gap-3 py-1 text-xs">{children}</div>;
}

/** 结论条：只用后端字段拼句子，缺一项就省一项，不做页面侧判断。 */
function conclusionText(summary: DashboardSummary): { facts: string[]; action: string | null } {
  const account = summary.account.data ?? null;
  const risk = summary.risk.data ?? null;
  const watchlist = summary.watchlist.data ?? null;
  const facts: string[] = [];

  const marginPct = num(account?.margin_usage_pct);
  if (marginPct !== null) facts.push(`保证金 ${marginPct.toFixed(0)}%`);

  const missingStop = num(risk?.missing_stop_count);
  if (missingStop !== null) facts.push(`缺止损 ${missingStop} 个`);

  const highLeverage = num(risk?.high_leverage_count);
  if (highLeverage !== null && highLeverage > 0) facts.push(`高杠杆 ${highLeverage} 个`);

  const watchlistTotal = num(watchlist?.summary.total);
  const watchlistBearish = num(watchlist?.summary.bearish);
  if (watchlistTotal !== null && watchlistBearish !== null) {
    facts.push(`自选 ${watchlistBearish}/${watchlistTotal} 走弱`);
  }

  const action =
    missingStop !== null && missingStop > 0
      ? "先处理止损"
      : highLeverage !== null && highLeverage > 0
        ? "先降杠杆"
        : risk === null
          ? null
          : "结构正常";
  return { facts, action };
}

export function HomeView({
  summary,
  error,
  loading,
  priceLiveness,
  accountLiveness,
  pushed,
  marketOverview,
  marketOverviewError,
  marketOverviewLoading,
  macroOverview,
  macroOverviewError,
  macroOverviewLoading,
  aiSummary,
  aiSummaryError,
  aiSummaryLoading,
  onRefresh,
  onResolveAlert,
  resolvingAlertId = null,
  pinnedWatchlist,
  watchlistCandidates,
  onSavePinned,
}: HomeViewProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  // 卡片行 = 置顶清单 ∩ 当前自选，价格用首页汇总里更实时的那一份覆盖。
  // 不能直接拿汇总里的行：汇总只带五行，置顶到第 6 个标的上会保存成功却渲染不出来。
  const pinnedRows = pinnedCardRows(
    watchlistCandidates,
    summary?.watchlist.data?.items ?? [],
    pinnedWatchlist,
  );

  const account = summary?.account.data ?? null;
  const risk = summary?.risk.data ?? null;
  const positions = summary?.positions.data ?? null;
  const watchlist = summary?.watchlist.data ?? null;
  // `null` = 模块不可用，`[]` = 模块可用但没有记录：区块正文对这两种状态要写不同的话。
  const alerts = summary?.alerts.data ?? null;
  const alertItems = alerts ?? [];
  const activity = summary?.activity.data ?? [];
  const strategies = summary?.strategies.data ?? null;
  const degraded = summary?.degraded ?? [];

  // 健康度：自选按涨跌幅绝对值降序，持仓按盈亏绝对值降序。
  const sortedWatchlist = [...pinnedRows].sort(
    (left, right) =>
      Math.abs(num(right.change_pct_24h) ?? 0) - Math.abs(num(left.change_pct_24h) ?? 0),
  );
  const sortedPositions = [...(positions?.items ?? [])].sort(
    (left, right) =>
      Math.abs(num(right.unrealized_pnl) ?? 0) - Math.abs(num(left.unrealized_pnl) ?? 0),
  );

  // 推送覆盖只算真的显示出来的自选行：没置顶时卡片是空的，写「N 条自选推送」
  // 会让人以为卡里还有数据。
  const displayedWatchlistIds = new Set(sortedWatchlist.map((item) => item.inst_id));
  const pushedWatchlistCount = Object.keys(pushed.watchlist).filter((instId) =>
    displayedWatchlistIds.has(instId),
  ).length;

  const conclusion = summary === null ? null : conclusionText(summary);
  const spread = macroOverview?.spread ?? null;
  const macroNotice = macroStaleNotice(macroOverview);
  const spreadUnavailable = spreadUnavailableText(spread);
  const riskLevel = riskLevelView(risk?.risk_level);

  // 同一个序列可能同时有分钟级与日结读数：只取后端选定的那一份，避免同一行出现两次。
  const macroRows: { label: string; value: string; detail: string; tone: string }[] = [];
  const us10y = primaryReading(macroOverview, "us10y");
  if (us10y !== null) {
    macroRows.push({
      label: us10y.name,
      value: readingValueText(us10y) ?? "缺失",
      detail: changeText(us10y) ?? "—",
      tone: tone(us10y.change),
    });
  }
  const vix = primaryReading(macroOverview, "vix");
  if (vix !== null) {
    macroRows.push({
      label: vix.name,
      value: readingValueText(vix) ?? "缺失",
      detail: `${changeText(vix) ?? "—"} · ${regimeLabel(vix.regime)}`,
      tone: regimeTone(vix.regime),
    });
  }
  const marketStale = marketOverview === null ? null : overviewStaleNotice(marketOverview);

  return (
    <>
      <PageHeading
        eyebrow="Trading overview"
        title="市场与账户"
        description="一屏判断今天要不要动手：先看结论，再看钱、标的、环境、待办与系统状态。"
        actions={
          <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            {loading ? "刷新中…" : "刷新"}
          </Button>
        }
      />

      {error ? (
        <p
          role="alert"
          className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      {summary === null ? (
        <p className="rounded-md border bg-card px-4 py-6 text-sm text-muted-foreground">
          {loading ? "正在读取首页汇总…" : "首页汇总不可用，请重试。"}
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <section
            data-block="conclusion"
            id="conclusion"
            className="min-w-0 rounded-lg border bg-card px-4 py-2.5 text-sm shadow-sm lg:col-span-12"
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span data-conclusion-facts className="font-mono tabular-nums">
                {conclusion?.facts.join(" · ")}
              </span>
              {conclusion?.action ? (
                <>
                  <span className="text-muted-foreground">→</span>
                  <span className="font-medium">{conclusion.action}</span>
                </>
              ) : null}
              {/* 持仓模块不可用时整项省略：不能把「没有数据」写成「同步异常」。 */}
              {positions === null ? null : (
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {positions.total} 个持仓 · 同步
                  {exchangeStatusLabel(positions.exchange_status)}
                </span>
              )}
            </div>
            <div className="mt-1 space-y-1">
              <StreamNotice liveness={priceLiveness} subject="关注列表价格" />
              <StreamNotice liveness={accountLiveness} subject="账户与持仓快照" />
            </div>
          </section>

          {degraded.length > 0 ? (
            <p
              role="status"
              className="rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400 lg:col-span-12"
            >
              以下模块降级：
              {degraded.map((item) => `${moduleTitle(item.module)}（${item.reason}）`).join("；")}
            </p>
          ) : null}

          <Panel
            block="account"
            title="资金与风险"
            hint={account ? `来源 ${account.source}` : undefined}
            className="lg:col-span-5"
          >
            {account === null ? (
              <p className="text-xs text-muted-foreground">账户数据不可用</p>
            ) : (
              <>
                <div className="font-mono text-2xl font-semibold tabular-nums">
                  {money(account.equity)}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {account.currency}
                  </span>
                </div>
                <div className={cn("mt-0.5 text-xs", tone(account.day_pnl))}>
                  今日 {money(account.day_pnl)} · 未实现 {money(account.unrealized_pnl)}
                </div>
                <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
                  <div
                    className="h-1.5 rounded-full bg-amber-500"
                    style={{ width: `${Math.min(Math.max(num(account.margin_usage_pct) ?? 0, 0), 100)}%` }}
                  />
                </div>
                <Row>
                  <span className="text-muted-foreground">保证金使用</span>
                  <span className="font-mono tabular-nums">
                    {num(account.margin_usage_pct) === null
                      ? "未提供"
                      : `${(num(account.margin_usage_pct) ?? 0).toFixed(2)}%`}{" "}
                    · 可用 {money(account.available_margin)}
                  </span>
                </Row>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                  {/* 风险数据缺失时不写 0：那会被读成「没有缺止损仓位、没有高杠杆」，
                      所以改用中性配色的「未提供」。 */}
                  {[
                    { label: "缺止损", value: num(risk?.missing_stop_count), tone: ALERT_BADGE },
                    { label: "高杠杆", value: num(risk?.high_leverage_count), tone: WARN_BADGE },
                  ].map((badge) => (
                    <span
                      key={badge.label}
                      className={cn(
                        "rounded border px-1.5 py-0.5",
                        badge.value === null ? "text-muted-foreground" : badge.tone,
                      )}
                    >
                      {badge.label} {badge.value === null ? "未提供" : badge.value}
                    </span>
                  ))}
                  <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                    最大单标的敞口{" "}
                    {num(risk?.max_single_instrument_weight_pct) === null
                      ? "未提供"
                      : `${(num(risk?.max_single_instrument_weight_pct) ?? 0).toFixed(2)}%`}
                  </span>
                  <span className={cn("rounded border px-1.5 py-0.5", riskLevel.tone)}>
                    风险等级 {riskLevel.label}
                  </span>
                </div>
              </>
            )}
          </Panel>

          <Panel
            block="watchlist"
            title="关注列表"
            hint={pinnedCountText(pinnedRows.length)}
            className="lg:col-span-7"
          >
            <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span data-watchlist-summary>
                {watchlist
                  ? `共 ${watchlist.summary.total} 个 · 偏多 ${watchlist.summary.bullish} · 偏空 ${watchlist.summary.bearish} · 覆盖率 ${watchlist.summary.coverage_pct}%`
                  : ""}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 px-1.5 text-[11px] text-muted-foreground"
                onClick={() => setPickerOpen(true)}
                disabled={summary.watchlist.data == null}
              >
                <Pencil className="h-3 w-3" aria-hidden="true" />
                编辑
              </Button>
            </div>
            {sortedWatchlist.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                {watchlist === null
                  ? "关注列表数据不可用"
                  : "还没有置顶标的，点「编辑」从自选里挑最多 5 个"}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs" data-sorted-rows="watchlist">
                  <thead>
                    <tr className="border-b text-[11px] text-muted-foreground">
                      <th className="py-1 text-left font-medium">标的</th>
                      <th className="py-1 text-right font-medium">价格</th>
                      <th className="py-1 text-right font-medium">涨跌</th>
                      <th className="py-1 text-right font-medium">RSI</th>
                      <th className="py-1 text-right font-medium">趋势</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedWatchlist.map((item) => (
                      <tr
                        key={item.inst_id}
                        data-inst-id={item.inst_id}
                        className="border-b last:border-0"
                      >
                        <td className="py-1.5 pr-2 font-mono">{item.display_symbol}</td>
                        <td className="py-1.5 text-right font-mono tabular-nums">
                          {money(item.last_price)}
                        </td>
                        <td
                          className={cn(
                            "py-1.5 text-right font-mono tabular-nums",
                            tone(item.change_pct_24h),
                          )}
                        >
                          {pct(item.change_pct_24h)}
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums">
                          {num(item.rsi_14) === null ? "—" : (num(item.rsi_14) ?? 0).toFixed(0)}
                        </td>
                        <td className="py-1.5 text-right">{trendText(item.trend)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel
            block="positions"
            title="当前持仓"
            hint={positions ? `${positions.total} 个 · 按盈亏绝对值排序` : undefined}
            className="lg:col-span-7"
          >
            {sortedPositions.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                {positions === null ? "持仓数据不可用" : "没有持仓"}
              </p>
            ) : (
              // 固定高度滚动：持仓再多也不把页面撑高。
              <div className="overflow-y-auto" style={{ maxHeight: "15rem" }}>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs" data-sorted-rows="positions">
                    <thead>
                      <tr className="border-b text-[11px] text-muted-foreground">
                        <th className="py-1 text-left font-medium">标的</th>
                        <th className="py-1 text-right font-medium">方向</th>
                        <th className="py-1 text-right font-medium">名义</th>
                        <th className="py-1 text-right font-medium">止损距离</th>
                        <th className="py-1 text-right font-medium">未实现</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedPositions.map((item) => (
                        <tr
                          key={item.position_ref}
                          data-position-ref={item.position_ref}
                          className="border-b last:border-0"
                        >
                          <td className="py-1.5 font-mono">
                            {item.display_symbol ?? item.inst_id}
                          </td>
                          <td className="py-1.5 text-right">
                            {item.side === "long" ? "多" : "空"}
                            {item.leverage === null || item.leverage === undefined
                              ? ""
                              : ` ${item.leverage}x`}
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {money(item.notional)}
                          </td>
                          <td className="py-1.5 text-right text-[11px] text-muted-foreground">
                            {num(item.stop_distance_pct) === null
                              ? "后端未返回"
                              : `距止损 ${pct(item.stop_distance_pct)}`}
                          </td>
                          <td
                            className={cn(
                              "py-1.5 text-right font-mono tabular-nums",
                              tone(item.unrealized_pnl),
                            )}
                          >
                            {signed(item.unrealized_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Panel>

          <Panel
            block="market"
            title="市场环境"
            hint={marketOverview === null ? undefined : `数据时间 ${asOfText(marketOverview.as_of)}`}
            className="lg:col-span-5"
          >
            <div className="space-y-0.5">
              {marketOverviewError !== null ? (
                <p role="alert" className="text-xs text-destructive">
                  {marketOverviewError}
                </p>
              ) : marketOverviewLoading && marketOverview === null ? (
                <p className="text-xs text-muted-foreground">正在读取市场概况…</p>
              ) : null}
              {marketStale ? (
                <p role="status" className="text-[11px] text-amber-700 dark:text-amber-400">
                  {marketStale}
                </p>
              ) : null}
              {(marketOverview?.items ?? []).map((item) => (
                <Row key={item.symbol}>
                  <span className="truncate text-muted-foreground">
                    {item.name}
                  </span>
                  <span className="shrink-0 font-mono tabular-nums">
                    {item.value ?? "—"}{" "}
                    <span className={tone(item.change_pct)}>{pct(item.change_pct)}</span>
                  </span>
                </Row>
              ))}
              {macroOverviewError !== null ? (
                <p role="alert" className="text-xs text-destructive">
                  {macroOverviewError}
                </p>
              ) : macroOverviewLoading && macroOverview === null ? (
                <p className="text-xs text-muted-foreground">正在读取宏观数据…</p>
              ) : null}
              {macroNotice ? (
                <p role="status" className="text-[11px] text-amber-700 dark:text-amber-400">
                  {macroNotice}
                </p>
              ) : null}
              {/* 一个序列同时有分钟级与日结读数，只显示后端选定的那一份，避免同一行出现两次。 */}
              {macroRows.map((row) => (
                <Row key={row.label}>
                  <span className="truncate text-muted-foreground">{row.label}</span>
                  <span className="shrink-0 font-mono tabular-nums">
                    {row.value}{" "}
                    <span className={row.tone}>{row.detail}</span>
                  </span>
                </Row>
              ))}
              {spread?.available ? (
                <Row>
                  <span className="text-muted-foreground">2Y→10Y 利差</span>
                  <span className={cn("font-mono tabular-nums", spreadTone(spread))}>
                    {spread?.inverted ? "倒挂 " : ""}
                    {spreadValueText(spread) ?? "不可用"}
                  </span>
                </Row>
              ) : spreadUnavailable !== null ? (
                <p className="text-[11px] text-muted-foreground">{spreadUnavailable}</p>
              ) : null}
              {aiSummaryError !== null ? (
                <p role="alert" className="text-xs text-destructive">
                  {aiSummaryError}
                </p>
              ) : aiSummaryLoading && aiSummary === null ? (
                <p className="text-xs text-muted-foreground">正在生成市场摘要…</p>
              ) : null}
              {aiSummary?.overall ? (
                <p className="mt-2 border-t pt-2 text-[11px] leading-5 text-muted-foreground">
                  {aiSummary.overall}
                </p>
              ) : null}
            </div>
          </Panel>

          <Panel
            block="alerts"
            title="提醒"
            hint={alertItems.length > 0 ? `共 ${alertItems.length} 条` : undefined}
            className="lg:col-span-7"
          >
            {alertItems.length === 0 ? (
              <p className="py-3 text-center text-xs text-muted-foreground">
                {alerts === null ? "提醒数据不可用" : "没有待处理的提醒"}
              </p>
            ) : (
              <div className="overflow-y-auto" style={{ maxHeight: "11rem" }}>
                {alertItems.map((alert) => (
                  <div
                    key={alert.id}
                    data-alert-id={alert.id}
                    className="flex items-start gap-2 border-b py-1.5 text-xs last:border-0"
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                        alert.severity === "critical"
                          ? "bg-rose-500"
                          : alert.severity === "warning"
                            ? "bg-amber-500"
                            : "bg-muted-foreground",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{alert.title}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {alert.instrument_id ?? "全局"} · {alert.type}
                      </div>
                    </div>
                    {onResolveAlert ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-1.5 text-[11px] text-muted-foreground"
                        disabled={resolvingAlertId === alert.id}
                        onClick={() => onResolveAlert(alert.id, "acknowledged")}
                      >
                        处理
                      </Button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel block="system" title="系统状态" className="lg:col-span-5">
            {/* 持仓模块不可用时省掉这一行；有数据时用后端枚举的中文标签，不打印原始值。 */}
            {positions === null ? null : (
              <Row>
                <span className="text-muted-foreground">持仓同步</span>
                <span className="font-mono">{exchangeStatusLabel(positions.exchange_status)}</span>
              </Row>
            )}
            <Row>
              <span className="text-muted-foreground">策略</span>
              <span className="font-mono">
                {strategies ? `${strategies.enabled} 启用 / ${strategies.total} 个` : "—"}
              </span>
            </Row>
            <Row>
              <span className="text-muted-foreground">推送覆盖</span>
              <span className="font-mono">
                {pushed.account === null ? "账户 HTTP" : "账户推送"} ·{" "}
                {Object.keys(pushed.positions).length} 条持仓推送 · {pushedWatchlistCount} 条自选推送
              </span>
            </Row>
            {activity.length > 0 ? (
              <div className="mt-2 border-t pt-2">
                {activity.slice(0, 3).map((item) => (
                  <div key={item.id} className="truncate text-[11px] text-muted-foreground">
                    {item.summary}
                  </div>
                ))}
              </div>
            ) : null}
          </Panel>
        </div>
      )}

      <WatchlistPicker
        open={pickerOpen}
        items={watchlistCandidates}
        pinned={pinnedWatchlist}
        onClose={() => setPickerOpen(false)}
        onSave={onSavePinned}
      />
    </>
  );
}
