/**
 * 首页各模块的内容区。只做展示：数值来自 `DashboardSummary`，按模块原样排版，
 * 不重算盈亏、风险等级或覆盖率。页面外壳与取数在 `pages/overview.tsx`。
 */

import { Link } from "react-router-dom";

import {
  amountText,
  asOfText,
  clampedPercent,
  countText,
  dataSourceLabel,
  dayPnlBasisLabel,
  exchangeStatusLabel,
  marketSessionLabel,
  percentOrMissingText,
  ratioPercentText,
  signedRatioPercentText,
  type DashboardSummary,
} from "../../lib/dashboard";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import { accountSourceLabel, positionSideLabel } from "../../lib/positions";
import { marginUsageBasisLabel, riskLevelView } from "../../lib/risk";
import { cn } from "../../lib/utils";

function Metric({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("mt-1 break-words font-mono text-sm tabular-nums", tone)} title={value}>
        {value}
      </dd>
      {note ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{note}</p> : null}
    </div>
  );
}

export function AccountBody({
  summary,
  pushedAt,
}: {
  summary: DashboardSummary;
  pushedAt: string | null;
}) {
  const data = summary.account.data;
  if (data == null) return null;
  const usage = clampedPercent(data.margin_usage_pct);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-4">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">账户权益</p>
          <p className="mt-1 break-words font-mono text-3xl font-semibold tracking-tight tabular-nums">
            {amountText(data.equity, data.currency)}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            账户 {data.account_id} · 来源 {accountSourceLabel(data.source)}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {pushedAt === null
              ? "权益、保证金与未实现盈亏：HTTP 快照"
              : `权益、保证金与未实现盈亏：推送 ${asOfText(pushedAt)}；今日盈亏仍为快照 ${asOfText(summary.account.as_of)}`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">今日盈亏</p>
          <p
            className={cn(
              "mt-1 font-mono text-base font-medium tabular-nums",
              data.day_pnl === null || data.day_pnl === undefined
                ? ""
                : signedTone(data.day_pnl),
            )}
          >
            {data.day_pnl === null || data.day_pnl === undefined
              ? "未提供"
              : `${signedValue(data.day_pnl)} ${data.currency}`}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            日盈亏基准：{dayPnlBasisLabel(data.day_pnl_basis)}
          </p>
        </div>
      </div>

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="可用保证金" value={amountText(data.available_margin, data.currency)} />
        <Metric label="已用保证金" value={amountText(data.used_margin, data.currency)} />
        <Metric
          label="未实现盈亏"
          value={amountText(data.unrealized_pnl, data.currency)}
          tone={
            data.unrealized_pnl === null || data.unrealized_pnl === undefined
              ? undefined
              : signedTone(data.unrealized_pnl)
          }
        />
        <Metric label="可用权益" value={amountText(data.available_equity, data.currency)} />
      </dl>

      <div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>保证金使用率</span>
          <span className="font-mono text-foreground tabular-nums">
            {percentOrMissingText(data.margin_usage_pct)}
          </span>
        </div>
        <div
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
          role="presentation"
        >
          <div
            className="h-full rounded-full bg-slate-500"
            style={{ width: usage === null ? "0%" : `${usage}%` }}
          />
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          已用 {amountText(data.used_margin, data.currency)} · 可用{" "}
          {amountText(data.available_margin, data.currency)}
        </p>
      </div>
    </div>
  );
}

export function RiskBody({ summary }: { summary: DashboardSummary }) {
  const data = summary.risk.data;
  if (data == null) return null;
  const level = riskLevelView(data.risk_level);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <div>
          <p className="text-xs text-muted-foreground">综合风险等级</p>
          <p className="mt-1 text-sm text-muted-foreground">
            由后端风险接口给出，页面不重新判定
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-4 py-1.5 text-base font-semibold",
            level.tone,
          )}
        >
          {level.label}
        </span>
      </div>
      <dl className="space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted-foreground">临近止损</dt>
          <dd className="font-mono tabular-nums">{countText(data.near_stop_count)} 个持仓</dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted-foreground">高杠杆仓位</dt>
          <dd className="font-mono tabular-nums">{countText(data.high_leverage_count)} 个</dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted-foreground">未设置止损</dt>
          <dd className="font-mono tabular-nums">{countText(data.missing_stop_count)} 个</dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted-foreground">最大单标的敞口</dt>
          <dd className="font-mono tabular-nums">
            {percentOrMissingText(data.max_single_instrument_weight_pct)}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted-foreground">保证金使用率</dt>
          <dd className="font-mono tabular-nums">{percentOrMissingText(data.margin_usage_pct)}</dd>
        </div>
      </dl>
      <p className="border-t pt-3 text-[11px] leading-5 text-muted-foreground">
        口径：{marginUsageBasisLabel(data.margin_usage_basis)} · 持仓{" "}
        {countText(data.position_count)} 个 · 多头{" "}
        {amountText(data.long_notional, data.currency)} · 空头{" "}
        {amountText(data.short_notional, data.currency)} · 净敞口{" "}
        {amountText(data.net_notional, data.currency)} · 名义价值合计{" "}
        {amountText(data.gross_notional, data.currency)}
      </p>
    </div>
  );
}

export function PositionsBody({
  summary,
  pushed,
}: {
  summary: DashboardSummary;
  pushed: Record<string, string>;
}) {
  const data = summary.positions.data;
  if (data == null) return null;
  const pushedAtList = [...new Set(Object.values(pushed).map((moment) => asOfText(moment)))];
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        共 {countText(data.total)} 个：OKX {countText(data.exchange_count)} 个 · 手动{" "}
        {countText(data.manual_count)} 个 · OKX 同步状态{" "}
        {exchangeStatusLabel(data.exchange_status)}
      </p>
      {data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">当前没有持仓。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-3 text-left font-medium">合约</th>
                <th className="px-2 py-2 text-left font-medium">方向 / 杠杆</th>
                <th className="px-2 py-2 text-right font-medium">未实现盈亏</th>
                <th className="px-2 py-2 text-right font-medium">标记价</th>
                <th className="py-2 pl-2 text-left font-medium">止损状态</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.position_ref} className="border-b last:border-0">
                  <td className="py-3 pr-3">
                    <Link
                      to="/positions"
                      className="font-mono text-xs underline-offset-4 hover:underline"
                    >
                      {item.display_symbol}
                    </Link>
                    <span className="block text-[11px] text-muted-foreground">
                      {item.source === "exchange" ? "OKX 快照" : "手动持仓"} ·{" "}
                      {item.inst_id}
                    </span>
                  </td>
                  <td className="px-2 py-3 text-xs">
                    {positionSideLabel(item.side)}
                    {item.leverage === null || item.leverage === undefined
                      ? ""
                      : ` · ${item.leverage}×`}
                  </td>
                  <td
                    className={cn(
                      "px-2 py-3 text-right font-mono text-xs tabular-nums",
                      item.unrealized_pnl === null || item.unrealized_pnl === undefined
                        ? ""
                        : signedTone(item.unrealized_pnl),
                    )}
                  >
                    {item.unrealized_pnl === null || item.unrealized_pnl === undefined
                      ? "未提供"
                      : signedValue(item.unrealized_pnl)}
                  </td>
                  <td className="px-2 py-3 text-right font-mono text-xs tabular-nums">
                    {item.mark_price ?? "未提供"}
                  </td>
                  <td className="py-3 pl-2 text-xs">
                    {item.stop_distance_pct === null ||
                    item.stop_distance_pct === undefined ||
                    item.stop_distance_pct.trim() === ""
                      ? "后端未返回止损距离"
                      : `距止损 ${percentOrMissingText(item.stop_distance_pct)}`}
                  </td>

                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] leading-5 text-muted-foreground">
        {pushedAtList.length === 0
          ? `标记价、未实现盈亏、名义价值与止损距离均为 HTTP 快照 ${asOfText(summary.positions.as_of)}。`
          : `标记价与未实现盈亏来自推送 ${pushedAtList.join("、")}；名义价值与止损距离仍是 HTTP 快照 ${asOfText(summary.positions.as_of)}。`}
      </p>
    </div>
  );
}

export function MarketBody({ summary }: { summary: DashboardSummary }) {
  const data = summary.market.data;
  if (data == null) return null;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        当前时段：{marketSessionLabel(data.session)}
      </p>
      {data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">后端没有返回标的类别。</p>
      ) : (
        <dl className="grid gap-3 sm:grid-cols-2">
          {data.items.map((item) => (
            <div key={item.inst_type} className="rounded-md border px-3 py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <dt className="text-sm font-medium">
                  {instTypeLabel(item.inst_type)} · {marketSessionLabel(item.session)}
                </dt>
                <dd className="text-[11px] text-muted-foreground">
                  {dataSourceLabel(item.primary_source)} · {item.bar}
                </dd>
              </div>
              <dd className="mt-2 text-xs leading-5 text-muted-foreground">
                上涨 {item.breadth.advancers} / 下跌 {item.breadth.decliners} / 平{" "}
                {item.breadth.unchanged} · 参与 {item.breadth.participants} 个 · 广度比{" "}
                {item.breadth.ratio ?? "未提供"} · 共振强度{" "}
                {ratioPercentText(item.resonance.strength)} · 窗口 {item.resonance.window} 根
              </dd>
              <dd className="mt-1 text-[11px] text-muted-foreground">
                行情时间：{asOfText(item.as_of)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export function WatchlistBody({
  summary,
  pushed,
}: {
  summary: DashboardSummary;
  pushed: Record<string, string>;
}) {
  const data = summary.watchlist.data;
  if (data == null) return null;
  const pushedAtList = [...new Set(Object.values(pushed).map((moment) => asOfText(moment)))];
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        共 {countText(data.summary.total)} 个 · 偏多 {countText(data.summary.bullish)} · 偏空{" "}
        {countText(data.summary.bearish)} · 日线覆盖率 {percentOrMissingText(data.summary.coverage_pct)}
      </p>
      {data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">自选列表为空。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-3 text-left font-medium">标的</th>
                <th className="px-2 py-2 text-right font-medium">价格</th>
                <th className="px-2 py-2 text-right font-medium">日涨跌</th>
                <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">RSI</th>
                <th className="py-2 pl-2 text-left font-medium">趋势</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.inst_id} className="border-b last:border-0">
                  <td className="py-3 pr-3">
                    <Link
                      to={`/watchlist/${encodeURIComponent(item.inst_id)}`}
                      className="font-mono text-xs underline-offset-4 hover:underline"
                    >
                      {item.display_symbol}
                    </Link>
                    <span className="block text-[11px] text-muted-foreground">{item.name}</span>
                  </td>
                  <td className="px-2 py-3 text-right font-mono text-xs tabular-nums">
                    {item.last_price ?? "未提供"}
                  </td>
                  <td
                    className={cn(
                      "px-2 py-3 text-right font-mono text-xs tabular-nums",
                      item.change_pct_24h === null || item.change_pct_24h === undefined
                        ? ""
                        : signedTone(item.change_pct_24h),
                    )}
                  >
                    {item.change_pct_24h === null || item.change_pct_24h === undefined
                      ? "未提供"
                      : `${signedValue(item.change_pct_24h)}%`}
                  </td>
                  <td className="hidden px-2 py-3 text-right font-mono text-xs tabular-nums sm:table-cell">
                    {item.rsi_14 ?? "未提供"}
                  </td>
                  <td className="py-3 pl-2 text-xs">
                    {item.trend === "bullish"
                      ? "偏多"
                      : item.trend === "bearish"
                        ? "偏空"
                        : item.trend === "neutral"
                          ? "中性"
                          : "未生成"}
                  </td>

                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] leading-5 text-muted-foreground">
        {pushedAtList.length === 0
          ? `价格、日涨跌、RSI 与趋势均为 HTTP 快照 ${asOfText(summary.watchlist.as_of)}。`
          : `价格来自推送 ${pushedAtList.join("、")}；日涨跌、RSI 与趋势仍是 HTTP 快照 ${asOfText(summary.watchlist.as_of)}。`}
      </p>
    </div>
  );
}

export function AlertsBody({ summary }: { summary: DashboardSummary }) {
  const alerts = summary.alerts;
  if (alerts.data === null || alerts.data === undefined) return null;
  if (alerts.data.length === 0) {
    return <p className="text-sm text-muted-foreground">没有待处理提醒。</p>;
  }
  return (
    <ul className="space-y-2">
      {alerts.data.map((item) => (
        <li key={item.id} className="rounded-md border px-3 py-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm font-medium">{item.title}</span>
            <span className="text-[11px] text-muted-foreground">
              {asOfText(item.triggered_at)}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{item.detail}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            规则 {item.rule_id}
            {item.instrument_id ? ` · 标的 ${item.instrument_id}` : ""}
            {item.severity ? ` · 级别 ${item.severity}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function ActivityBody({ summary }: { summary: DashboardSummary }) {
  const activity = summary.activity;
  if (activity.data === null || activity.data === undefined) return null;
  if (activity.data.length === 0) {
    return <p className="text-sm text-muted-foreground">没有最近活动。</p>;
  }
  return (
    <ul className="space-y-1.5">
      {activity.data.map((item) => (
        <li key={item.id} className="flex items-baseline justify-between gap-3 text-xs">
          <span className="min-w-0 break-words">{item.summary}</span>
          <time className="shrink-0 text-muted-foreground">
            {asOfText(item.created_at)}
          </time>
        </li>
      ))}
    </ul>
  );
}

export function StrategiesBody({ summary }: { summary: DashboardSummary }) {
  const data = summary.strategies.data;
  if (data == null) return null;
  const recent = data.recent_backtest;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="策略总数" value={countText(data.total)} />
        <Metric label="已启用" value={countText(data.enabled)} />
        <Metric label="运行中" value={countText(data.running)} />
        <Metric label="待确认信号" value={countText(data.pending_signals)} />
      </dl>
      <div className="border-t pt-3">
        <p className="text-xs text-muted-foreground">最近 30 天回测</p>
        {recent === null || recent === undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">最近没有回测记录。</p>
        ) : (
          <>
            <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric
                label="总收益率"
                value={signedRatioPercentText(recent.total_return)}
                tone={signedTone(recent.total_return)}
              />
              <Metric label="最大回撤" value={ratioPercentText(recent.max_drawdown)} />
              <Metric label="交易次数" value={countText(recent.trade_count)} />
              <Metric label="回测窗口" value={`${countText(recent.window_days)} 天`} />
            </dl>
            <p className="mt-2 text-[11px] text-muted-foreground">
              回测 {recent.run_id} · 数据源 {dataSourceLabel(recent.data_source)} · 生成时间{" "}
              {asOfText(recent.as_of)}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

/** 市场摘要的后端能力由 S6-1 交付；交付前如实标注不可用，不拼摘要文案。 */
export function MarketSummaryBody() {
  return (
    <p
      role="status"
      className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
    >
      不可用（后端尚未提供市场摘要数据）
    </p>
  );
}

