import { Pencil, RefreshCw } from "lucide-react";
import { useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import { StreamNotice } from "../../components/ui/stream-status";
import { moduleTitle } from "../../lib/dashboard";
import { pinnedCardRows, pinnedCountText } from "../../lib/home-pinned";
import type { OverviewViewProps } from "./view";
import { WatchlistPicker } from "./watchlist-picker";

function num(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: string | null | undefined): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return parsed.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

function Panel({
  title,
  hint,
  children,
  className = "",
  id,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={`min-w-0 rounded-lg border bg-card text-card-foreground shadow-sm ${className}`}
      style={{ scrollMarginTop: "3.5rem" }}
    >
      <header className="flex items-baseline justify-between gap-3 px-4 pt-3">
        <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
        {hint ? <span className="text-[11px] text-muted-foreground">{hint}</span> : null}
      </header>
      <div className="px-4 pb-4 pt-2">{children}</div>
    </section>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex items-baseline justify-between gap-3 py-1 text-xs">{children}</div>;
}

/** 首页重设计：按「结论 → 钱 → 标的 → 环境 → 待办 → 系统」排，不是八张等权卡片。 */
export function HomeView({
  summary,
  error,
  loading,
  priceLiveness,
  accountLiveness,
  pushed,
  marketOverview,
  macroOverview,
  aiSummary,
  onRefresh,
  onResolveAlert,
  resolvingAlertId = null,
  pinnedWatchlist,
  watchlistCandidates,
  onSavePinned,
}: OverviewViewProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const pinnedRows = pinnedCardRows(
    watchlistCandidates,
    summary?.watchlist.data?.items ?? [],
    pinnedWatchlist,
  );

  const account = summary?.account.data ?? null;
  const risk = summary?.risk.data ?? null;
  const positions = summary?.positions.data ?? null;
  const watchlist = summary?.watchlist.data ?? null;
  const alerts = summary?.alerts.data ?? [];
  const activity = summary?.activity.data ?? [];
  const strategies = summary?.strategies.data ?? null;
  const degraded = summary?.degraded ?? [];

  const marginPct = num(account?.margin_usage_pct) ?? 0;
  const sortedPositions = [...(positions?.items ?? [])].sort(
    (left, right) => Math.abs(num(right.unrealized_pnl) ?? 0) - Math.abs(num(left.unrealized_pnl) ?? 0),
  );
  const sortedPinned = [...pinnedRows].sort(
    (left, right) => Math.abs(num(right.change_pct_24h) ?? 0) - Math.abs(num(left.change_pct_24h) ?? 0),
  );
  const sortedAlerts = [...alerts].sort((left, right) => {
    const weight: Record<string, number> = { critical: 0, warning: 1, info: 2 };
    return (weight[left.severity ?? "info"] ?? 3) - (weight[right.severity ?? "info"] ?? 3);
  });

  // 结论行只用后端返回的数字拼句子，不在这里做新的计算口径。
  const headline: string[] = [];
  if (account) headline.push(`保证金 ${Number(account.margin_usage_pct).toFixed(0)}%`);
  if (risk) {
    headline.push(`缺止损 ${risk.missing_stop_count} 个`);
    if (risk.high_leverage_count > 0) headline.push(`高杠杆 ${risk.high_leverage_count} 个`);
  }
  if (watchlist) headline.push(`自选 ${watchlist.summary.bearish}/${watchlist.summary.total} 走弱`);
  const action =
    (risk?.missing_stop_count ?? 0) > 0
      ? "先处理止损"
      : (risk?.high_leverage_count ?? 0) > 0
        ? "先降杠杆"
        : "结构正常";

  const macroReadings = macroOverview?.readings ?? [];
  const spread = macroOverview?.spread ?? null;

  return (
    <>
      <PageHeading
        eyebrow="Trading overview"
        title="市场与账户"
        description="一屏判断今天要不要动手：结论 → 资金与风险 → 标的异动 → 市场环境 → 待办与系统状态。"
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
          className="mb-3 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      {summary === null ? (
        <p className="rounded-md border bg-card px-4 py-6 text-sm text-muted-foreground">
          {loading ? "正在读取首页汇总…" : "首页汇总不可用，请重试。"}
        </p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-12">
          <div className="lg:col-span-12 rounded-lg border bg-card px-4 py-2.5 text-sm shadow-sm">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-mono tabular-nums">{headline.join(" · ")}</span>
              <span className="text-muted-foreground">→</span>
              <span className="font-medium">{action}</span>
              <span className="ml-auto text-[11px] text-muted-foreground">
                {positions ? `${positions.total} 个持仓 · ` : ""}
                同步{positions?.exchange_status === "ok" ? "正常" : "异常"}
              </span>
            </div>
            <div className="mt-1 space-y-1">
              <StreamNotice liveness={priceLiveness} subject="关注列表价格" />
              <StreamNotice liveness={accountLiveness} subject="账户与持仓快照" />
            </div>
          </div>

          {degraded.length > 0 ? (
            <p
              role="status"
              className="lg:col-span-12 rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400"
            >
              以下模块降级：
              {degraded.map((item) => `${moduleTitle(item.module)}（${item.reason}）`).join("；")}
            </p>
          ) : null}

          <Panel
            id="account"
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
                <div className={`mt-0.5 text-xs ${tone(account.day_pnl)}`}>
                  今日 {money(account.day_pnl)} · 未实现 {money(account.unrealized_pnl)}
                </div>
                <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
                  <div
                    className="h-1.5 rounded-full bg-amber-500"
                    style={{ width: `${Math.min(Math.max(marginPct, 0), 100)}%` }}
                  />
                </div>
                <Row>
                  <span className="text-muted-foreground">保证金使用</span>
                  <span className="font-mono tabular-nums">
                    {account.margin_usage_pct}% · 可用 {money(account.available_margin)}
                  </span>
                </Row>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                  <span className="rounded border border-rose-600/40 bg-rose-500/5 px-1.5 py-0.5 text-rose-700 dark:text-rose-400">
                    缺止损 {risk?.missing_stop_count ?? 0}
                  </span>
                  <span className="rounded border border-amber-600/40 bg-amber-500/5 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">
                    高杠杆 {risk?.high_leverage_count ?? 0}
                  </span>
                  <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                    最大单标的敞口 {risk?.max_single_instrument_weight_pct ?? "—"}%
                  </span>
                  <span className="rounded border px-1.5 py-0.5 text-muted-foreground">
                    风险等级 {risk?.risk_level ?? "—"}
                  </span>
                </div>
              </>
            )}
          </Panel>

          <Panel
            id="watchlist"
            title="关注列表"
            hint={pinnedCountText(pinnedRows.length)}
            className="lg:col-span-7"
          >
            <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span>
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
              >
                <Pencil className="h-3 w-3" aria-hidden="true" />
                编辑
              </Button>
            </div>
            {sortedPinned.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                还没有置顶标的，点「编辑」从自选里挑最多 5 个
              </p>
            ) : (
              <table className="w-full text-xs">
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
                  {sortedPinned.map((item) => (
                    <tr key={item.inst_id} className="border-b last:border-0">
                      <td className="py-1.5 pr-2 font-mono">{item.display_symbol}</td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {money(item.last_price)}
                      </td>
                      <td className={`py-1.5 text-right font-mono tabular-nums ${tone(item.change_pct_24h)}`}>
                        {pct(item.change_pct_24h)}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {item.rsi_14 === null ? "—" : Number(item.rsi_14).toFixed(0)}
                      </td>
                      <td className="py-1.5 text-right">{trendText(item.trend)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel
            id="positions"
            title="当前持仓"
            hint={positions ? `${positions.total} 个 · 按盈亏绝对值排序` : undefined}
            className="lg:col-span-7"
          >
            {sortedPositions.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">没有持仓</p>
            ) : (
              <div className="overflow-y-auto" style={{ maxHeight: "15rem" }}>
                <table className="w-full text-xs">
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
                      <tr key={item.position_ref} className="border-b last:border-0">
                        <td className="py-1.5 font-mono">
                          {item.display_symbol ?? item.inst_id}
                        </td>
                        <td className="py-1.5 text-right">
                          {item.side === "long" ? "多" : "空"} {item.leverage}x
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums">
                          {money(item.notional)}
                        </td>
                        <td className="py-1.5 text-right text-[11px] text-muted-foreground">
                          {item.stop_distance_pct === null
                            ? "后端未返回"
                            : `距止损 ${item.stop_distance_pct}%`}
                        </td>
                        <td className={`py-1.5 text-right font-mono tabular-nums ${tone(item.unrealized_pnl)}`}>
                          {money(item.unrealized_pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel id="market-overview" title="市场环境" className="lg:col-span-5">
            <div className="space-y-0.5">
              {(marketOverview?.items ?? []).map((item) => (
                <Row key={item.symbol}>
                  <span className="text-muted-foreground">{item.name}</span>
                  <span className="font-mono tabular-nums">
                    {item.value}{" "}
                    <span className={tone(item.change_pct)}>{pct(item.change_pct)}</span>
                  </span>
                </Row>
              ))}
              {macroReadings.map((reading) => (
                <Row key={`${reading.series_id}-${reading.as_of}`}>
                  <span className="text-muted-foreground">{reading.name}</span>
                  <span className="font-mono tabular-nums">
                    {reading.value}
                    {reading.unit === "%" ? "%" : ` ${reading.unit}`}{" "}
                    <span className={tone(reading.change)}>
                      {(num(reading.change) ?? 0) > 0 ? "+" : ""}
                      {reading.change}
                    </span>
                  </span>
                </Row>
              ))}
              {spread?.available ? (
                <Row>
                  <span className="text-muted-foreground">2Y→10Y 利差</span>
                  <span className="font-mono tabular-nums">
                    {spread.inverted ? "倒挂 " : "+"}
                    {spread.value_bp}bp
                  </span>
                </Row>
              ) : null}
              {aiSummary?.overall ? (
                <p className="mt-2 border-t pt-2 text-[11px] leading-relaxed text-muted-foreground">
                  {aiSummary.overall}
                </p>
              ) : null}
            </div>
          </Panel>

          <Panel
            id="alerts"
            title="提醒"
            hint={alerts.length > 0 ? `共 ${alerts.length} 条` : undefined}
            className="lg:col-span-7"
          >
            {sortedAlerts.length === 0 ? (
              <p className="py-3 text-center text-xs text-muted-foreground">没有待处理的提醒</p>
            ) : (
              <div className="overflow-y-auto" style={{ maxHeight: "11rem" }}>
                {sortedAlerts.map((alert) => (
                  <div
                    key={alert.id}
                    className="flex items-start gap-2 border-b py-1.5 text-xs last:border-0"
                  >
                    <span
                      className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                        alert.severity === "critical"
                          ? "bg-rose-500"
                          : alert.severity === "warning"
                            ? "bg-amber-500"
                            : "bg-muted-foreground"
                      }`}
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

          <Panel title="系统状态" className="lg:col-span-5">
            <Row>
              <span className="text-muted-foreground">持仓同步</span>
              <span className="font-mono">{positions?.exchange_status ?? "—"}</span>
            </Row>
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
                {Object.keys(pushed.positions).length} 条持仓推送
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
