import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CandlestickChart } from "../components/chart/candlestick-chart";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import {
  fetchInstrumentAnalysis,
  fetchWatchlist,
  type InstrumentAnalysisBar,
  type InstrumentAnalysisCorrelation,
  type InstrumentAnalysisCoverage,
  type InstrumentAnalysisIndicators,
  type InstrumentAnalysisLinkedBacktest,
  type InstrumentAnalysisResponse,
  type WatchlistResponse,
} from "../lib/api";
import {
  assetTypeLabel,
  formatBeijingTime,
  instTypeLabel,
  priceChangeValue,
  signedTone,
  signedValue,
} from "../lib/display";
import { resolveAvailableBar } from "../lib/instrument";
import { cn } from "../lib/utils";

const BAR_OPTIONS: Array<{ bar: InstrumentAnalysisBar; label: string }> = [
  { bar: "1d", label: "1D" },
  { bar: "4h", label: "4H" },
  { bar: "1h", label: "1H" },
];

const BAR_LABELS: Record<InstrumentAnalysisBar, string> = {
  "1d": "日线",
  "4h": "4 小时",
  "1h": "1 小时",
};

const DATA_SOURCE_LABELS: Record<string, string> = {
  okx: "OKX",
  okx_spot: "OKX 现货",
  okx_swap: "OKX 永续",
  us_equity_proxy: "美股代理行情",
};

const PLACEHOLDER = "未生成";
const NOT_SYNCED = "尚未同步";

function sourceLabel(source: string): string {
  return DATA_SOURCE_LABELS[source] ?? source;
}

/** 只做显示精度与正负号，数值本身原样来自后端。 */
function percentLabel(value: string | null | undefined, fallback = PLACEHOLDER): string {
  if (value == null) return fallback;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${signedValue(number.toFixed(2))}%`;
}

/** 只做显示精度，数值本身原样来自后端。 */
function numberLabel(
  value: string | null | undefined,
  places = 2,
  fallback = PLACEHOLDER,
): string {
  if (value == null) return fallback;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number.toFixed(places);
}

/** 后端不可达时 fetch 抛 TypeError；换成用户能看懂的中文提示。 */
function loadErrorMessage(reason: unknown): string {
  if (reason instanceof Error) {
    if (reason.name === "TypeError" || reason.message === "Failed to fetch") {
      return "无法连接后端服务，请检查服务是否可用后重试。";
    }
    return reason.message;
  }
  return "分析数据加载失败";
}

function valueTone(value: string | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  return signedTone(value);
}

function Fact({
  label,
  value,
  tone,
  mono = true,
}: {
  label: string;
  value: string;
  tone?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 last:border-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("text-sm", mono && "font-mono tabular-nums", tone)}>{value}</dd>
    </div>
  );
}

function MetricCard({
  title,
  subtitle,
  facts,
}: {
  title: string;
  subtitle: string;
  facts: Array<{ label: string; value: string; tone?: string }>;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-baseline justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <span className="text-xs text-muted-foreground">{subtitle}</span>
        </div>
      </CardHeader>
      <CardContent>
        <dl>
          {facts.map((fact) => (
            <Fact key={fact.label} {...fact} />
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function TrendCard({ indicators }: { indicators: InstrumentAnalysisIndicators }) {
  const trend = indicators.trend;
  return (
    <MetricCard
      title="趋势"
      subtitle="MA20 / MA60"
      facts={[
        { label: "收盘价 close", value: numberLabel(trend.close) },
        { label: "MA20", value: numberLabel(trend.ma20) },
        { label: "MA60", value: numberLabel(trend.ma60) },
        {
          label: "价格与 MA20 距离",
          value: percentLabel(trend.price_vs_ma20_pct),
          tone: valueTone(trend.price_vs_ma20_pct),
        },
        {
          label: "价格与 MA60 距离",
          value: percentLabel(trend.price_vs_ma60_pct),
          tone: valueTone(trend.price_vs_ma60_pct),
        },
        {
          label: `MA20 ${trend.slope_window} 根斜率`,
          value: percentLabel(trend.ma20_slope_pct),
          tone: valueTone(trend.ma20_slope_pct),
        },
        {
          label: `MA60 ${trend.slope_window} 根斜率`,
          value: percentLabel(trend.ma60_slope_pct),
          tone: valueTone(trend.ma60_slope_pct),
        },
      ]}
    />
  );
}

function MomentumCard({ indicators }: { indicators: InstrumentAnalysisIndicators }) {
  const momentum = indicators.momentum;
  return (
    <MetricCard
      title="动量"
      subtitle="RSI(14) / MACD(12,26,9)"
      facts={[
        { label: "RSI(14)", value: numberLabel(momentum.rsi14) },
        { label: "MACD", value: numberLabel(momentum.macd, 4) },
        { label: "信号线", value: numberLabel(momentum.macd_signal, 4) },
        { label: "柱状值", value: numberLabel(momentum.macd_hist, 4) },
      ]}
    />
  );
}

function VolatilityCard({ indicators }: { indicators: InstrumentAnalysisIndicators }) {
  const volatility = indicators.volatility;
  return (
    <MetricCard
      title="波动"
      subtitle="ATR(14)"
      facts={[
        { label: "ATR(14)", value: numberLabel(volatility.atr14, 4) },
        { label: "ATR / 收盘价", value: percentLabel(volatility.atr_pct).replace("+", "") },
        {
          label: "20 日均值",
          value: percentLabel(volatility.atr_pct_avg20).replace("+", ""),
        },
      ]}
    />
  );
}

function VolumeCard({ indicators }: { indicators: InstrumentAnalysisIndicators }) {
  const volume = indicators.volume;
  return (
    <MetricCard
      title="成交量"
      subtitle="20 根均量"
      facts={[
        { label: "当前成交量", value: numberLabel(volume.current) },
        { label: "20 日均量", value: numberLabel(volume.average20) },
        { label: "相对成交量", value: numberLabel(volume.relative) },
      ]}
    />
  );
}

function RelativeStrengthCard({ indicators }: { indicators: InstrumentAnalysisIndicators }) {
  const relative = indicators.relative_strength;
  return (
    <MetricCard
      title="相对强弱"
      subtitle={relative.benchmark_inst_id ? `基准 ${relative.benchmark_inst_id}` : "基准未登记"}
      facts={[
        { label: `标的 ${relative.window} 日收益`, value: percentLabel(relative.symbol_return_pct) },
        {
          label: `基准 ${relative.window} 日收益`,
          value: percentLabel(relative.benchmark_return_pct),
        },
        {
          label: "超额收益",
          value: percentLabel(relative.excess_return_pct),
          tone: valueTone(relative.excess_return_pct),
        },
      ]}
    />
  );
}

function CorrelationRow({ row }: { row: InstrumentAnalysisCorrelation }) {
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className="py-2 pr-4">
        <span className="font-mono text-sm">{row.inst_id}</span>
        <span className="ml-2 text-xs text-muted-foreground">{row.product_key}</span>
      </td>
      <td className="py-2 pr-4 text-xs text-muted-foreground">
        {row.role === "benchmark" ? "基准" : "关联资产"}
      </td>
      <td className={cn("py-2 pr-4 font-mono text-sm tabular-nums", valueTone(row.coefficient))}>
        {row.coefficient == null ? "样本不足" : numberLabel(row.coefficient)}
      </td>
      <td className="py-2 pr-4 font-mono text-sm tabular-nums">
        {row.sample_size === 0 ? "未生成" : row.sample_size}
      </td>
      <td className="py-2 text-xs text-muted-foreground">
        {row.window} 日
        {row.window_start && row.window_end
          ? ` · ${formatBeijingTime(row.window_start, false)} ~ ${formatBeijingTime(
              row.window_end,
              false,
            )}`
          : ""}
      </td>
    </tr>
  );
}

function LinkedStrategyRow({ row }: { row: InstrumentAnalysisLinkedBacktest }) {
  const navigate = useNavigate();
  const target = `/backtests?run=${encodeURIComponent(row.run_id)}`;
  return (
    <tr
      tabIndex={0}
      onClick={() => navigate(target)}
      onKeyDown={(event) => {
        if (event.key === "Enter") navigate(target);
      }}
      className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-accent/40 focus-visible:bg-accent/40 focus-visible:outline-none"
    >
      <td className="py-3 pr-4">
        <Link
          to={target}
          onClick={(event) => event.stopPropagation()}
          className="font-medium underline-offset-4 hover:underline"
        >
          {row.strategy_name}
        </Link>
        <p className="text-xs text-muted-foreground">
          {row.strategy_id} · {sourceLabel(row.data_source)}
        </p>
      </td>
      <td className="py-3 pr-4 text-xs text-muted-foreground">
        {row.backtest_start_date} ~ {row.backtest_end_date}
      </td>
      <td className={cn("py-3 pr-4 text-right font-mono text-sm", valueTone(row.total_return_pct))}>
        {percentLabel(row.total_return_pct)}
      </td>
      <td className="py-3 pr-4 text-right font-mono text-sm">
        {percentLabel(row.max_drawdown_pct).replace("+", "")}
      </td>
      <td className="py-3 pr-4 text-right font-mono text-sm">{row.trade_count}</td>
      <td className="py-3 pr-4 text-xs text-muted-foreground">
        {formatBeijingTime(row.created_at, false)}
      </td>
      <td className="py-3 text-right text-xs">
        <Link
          to={target}
          onClick={(event) => event.stopPropagation()}
          className="text-primary underline-offset-4 hover:underline"
        >
          回测记录 →
        </Link>
      </td>
    </tr>
  );
}

function CoverageRow({ row }: { row: InstrumentAnalysisCoverage }) {
  const range =
    row.available_from && row.available_to
      ? `${formatBeijingTime(row.available_from, false)} ~ ${formatBeijingTime(
          row.available_to,
          false,
        )}`
      : NOT_SYNCED;
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className="py-2 pr-4 text-sm">{BAR_LABELS[row.bar]}</td>
      <td className="py-2 pr-4 text-xs text-muted-foreground">{sourceLabel(row.data_source)}</td>
      <td className="py-2 pr-4 text-xs text-muted-foreground">{range}</td>
      <td className="py-2 pr-4 text-right font-mono text-sm">
        {row.candle_count === 0 ? NOT_SYNCED : `${row.candle_count} 根`}
      </td>
      <td className="py-2 pr-4 text-right font-mono text-sm">
        {row.candle_count === 0 ? "未生成" : `${row.gap_count} 个`}
      </td>
      <td className="py-2 pr-4 text-xs text-muted-foreground">
        {row.last_synced_at ? formatBeijingTime(row.last_synced_at) : NOT_SYNCED}
      </td>
      <td className="py-2 text-xs">
        {row.available ? (
          <span className="text-emerald-600 dark:text-emerald-400">可用</span>
        ) : (
          <span className="text-amber-600 dark:text-amber-400">
            {row.unavailable_reason ?? NOT_SYNCED}
          </span>
        )}
      </td>
    </tr>
  );
}

export default function InstrumentDetailPage() {
  const { instId = "" } = useParams<{ instId: string }>();
  const navigate = useNavigate();
  const [bar, setBar] = useState<InstrumentAnalysisBar>("1d");
  const [analysis, setAnalysis] = useState<InstrumentAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [slowLoading, setSlowLoading] = useState(false);
  const [watchlist, setWatchlist] = useState<WatchlistResponse | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetchWatchlist()
      .then(setWatchlist)
      .catch(() => setWatchlist(null));
  }, []);

  useEffect(() => {
    if (!instId) return;
    let active = true;
    setLoading(true);
    setError(null);
    setAnalysis(null);
    fetchInstrumentAnalysis(instId, bar)
      .then((value) => {
        if (!active) return;
        const nextBar = resolveAvailableBar(value.coverage, bar);
        if (nextBar !== bar) {
          setBar(nextBar);
          return;
        }
        setAnalysis(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(loadErrorMessage(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [instId, bar]);

  useEffect(() => {
    if (!loading) {
      setSlowLoading(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowLoading(true), 15000);
    return () => window.clearTimeout(timer);
  }, [loading]);

  const group = useMemo(() => {
    const current = watchlist?.items.find((item) => item.instrument.inst_id === instId);
    return current?.group ?? null;
  }, [watchlist, instId]);

  const candidates = useMemo(() => {
    const items = watchlist?.items ?? [];
    const scoped = group === null ? items : items.filter((item) => item.group === group);
    const needle = query.trim().toLowerCase();
    if (needle === "") return scoped;
    return scoped.filter(
      (item) =>
        item.instrument.inst_id.toLowerCase().includes(needle) ||
        item.instrument.product_key.toLowerCase().includes(needle),
    );
  }, [watchlist, group, query]);

  const coverageByBar = useMemo(() => {
    const map = new Map<InstrumentAnalysisBar, InstrumentAnalysisCoverage>();
    for (const row of analysis?.coverage ?? []) map.set(row.bar, row);
    return map;
  }, [analysis]);

  const instrument = analysis?.instrument;
  const quote = analysis?.quote;
  const last = quote?.last ?? null;
  const currentCoverage = coverageByBar.get(bar);
  const candles = analysis?.candles;
  const indicators = analysis?.indicators;
  const levels = analysis?.levels;
  const correlations = analysis?.correlations ?? [];
  const linked = analysis?.linked_strategies ?? [];

  const pickInstrument = (nextId: string) => {
    setPickerOpen(false);
    setQuery("");
    navigate(`/watchlist/${encodeURIComponent(nextId)}`);
  };

  return (
    <>
      <div className="mb-4 overflow-x-auto">
        <nav
          aria-label="面包导航"
          className="flex min-w-max items-center gap-2 text-sm text-muted-foreground"
        >
          <Link to="/watchlist" className="underline-offset-4 hover:text-foreground hover:underline">
            自选
          </Link>
          <span aria-hidden="true" className="opacity-50">
            /
          </span>
          <div className="relative">
            <button
              type="button"
              aria-expanded={pickerOpen}
              aria-haspopup="listbox"
              onClick={() => setPickerOpen((open) => !open)}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border bg-card px-2.5 text-xs font-semibold text-foreground hover:bg-accent"
            >
              <span className="font-mono">{instId}</span>
              <span aria-hidden="true" className="opacity-60">
                ▾
              </span>
            </button>
            {pickerOpen ? (
              <>
                <button
                  type="button"
                  aria-label="关闭标的切换"
                  className="fixed inset-0 z-40 cursor-default"
                  onClick={() => setPickerOpen(false)}
                />
                <div className="absolute left-0 top-9 z-50 w-[min(22rem,calc(100vw-2rem))] rounded-lg border bg-card p-3 shadow-lg">
                  <p className="mb-2 text-xs text-muted-foreground">
                    {group === null ? "自选标的 · 快捷切换" : `自选分组「${group}」· 快捷切换`}
                  </p>
                  <input
                    autoFocus
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="搜索合约 ID 或产品键"
                    className="mb-2 h-8 w-full rounded-md border border-input bg-transparent px-2.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  <div role="listbox" className="max-h-64 overflow-y-auto">
                    {candidates.length === 0 ? (
                      <p className="px-1 py-3 text-xs text-muted-foreground">没有匹配的自选标的。</p>
                    ) : (
                      candidates.map((item) => (
                        <button
                          key={item.instrument.inst_id}
                          type="button"
                          role="option"
                          aria-selected={item.instrument.inst_id === instId}
                          onClick={() => pickInstrument(item.instrument.inst_id)}
                          className={cn(
                            "flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left text-xs hover:bg-accent",
                            item.instrument.inst_id === instId && "bg-accent/60",
                          )}
                        >
                          <span className="font-mono">{item.instrument.inst_id}</span>
                          <span className="text-muted-foreground">
                            {item.instrument.product_key} · {instTypeLabel(item.instrument.inst_type)}
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                  <Link
                    to="/watchlist"
                    className="mt-2 block border-t pt-2 text-xs text-primary underline-offset-4 hover:underline"
                  >
                    搜索并添加标的 →
                  </Link>
                </div>
              </>
            ) : null}
          </div>
        </nav>
      </div>

      {error ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {!analysis && loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          <p>加载中…</p>
          {slowLoading ? (
            <p className="mt-2 text-xs">加载时间过长，请检查后端服务是否可用。</p>
          ) : null}
        </div>
      ) : null}

      {analysis && instrument ? (
        <div className="grid grid-cols-1 gap-6">
          <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                {instrument.product_key}
                <span className="ml-1.5 text-sm font-normal text-muted-foreground">
                  / {instrument.quote_currency}
                </span>
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {assetTypeLabel(instrument.asset_type)} · {instTypeLabel(instrument.inst_type)} ·
                计价 {instrument.quote_currency} · <span className="font-mono">{instrument.inst_id}</span>
              </p>
            </div>
            <div className="grid min-w-0 gap-3 lg:justify-items-end">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                    最新价 last
                  </p>
                  <p className="font-mono text-3xl font-semibold tabular-nums">
                    {last ? last.price : NOT_SYNCED}
                  </p>
                  {last ? (
                    <p className={cn("text-sm font-medium", valueTone(last.change_pct))}>
                      {last.change == null ? PLACEHOLDER : priceChangeValue(last.change, last.price)}
                      {last.change_pct == null ? "" : ` (${percentLabel(last.change_pct)})`}
                    </p>
                  ) : null}
                </div>
                <div className="flex gap-1" role="group" aria-label="周期">
                  {BAR_OPTIONS.map((option) => {
                    const coverage = coverageByBar.get(option.bar);
                    const disabled = coverage ? !coverage.available : true;
                    return (
                      <Button
                        key={option.bar}
                        type="button"
                        size="sm"
                        variant={option.bar === bar ? "default" : "outline"}
                        disabled={disabled}
                        aria-pressed={option.bar === bar}
                        title={
                          disabled
                            ? (coverage?.unavailable_reason ?? NOT_SYNCED)
                            : `${BAR_LABELS[option.bar]}已同步`
                        }
                        onClick={() => setBar(option.bar)}
                      >
                        {option.label}
                      </Button>
                    );
                  })}
                </div>
              </div>
              <dl className="grid w-full gap-x-4 gap-y-1 text-xs sm:grid-cols-2 lg:w-[24rem]">
                <div className="flex min-w-0 gap-2">
                  <dt className="shrink-0 text-muted-foreground">标记价 mark</dt>
                  <dd className="font-mono">{quote?.mark?.price ?? "尚未提供"}</dd>
                </div>
                <div className="flex min-w-0 gap-2">
                  <dt className="shrink-0 text-muted-foreground">指数价 index</dt>
                  <dd className="font-mono">{quote?.index?.price ?? "尚未提供"}</dd>
                </div>
                <div className="flex min-w-0 gap-2">
                  <dt className="shrink-0 text-muted-foreground">数据时间</dt>
                  <dd className="font-mono">
                    {last ? `${formatBeijingTime(last.as_of)}（北京时间）` : NOT_SYNCED}
                  </dd>
                </div>
                <div className="flex min-w-0 gap-2">
                  <dt className="shrink-0 text-muted-foreground">价格来源</dt>
                  <dd className="font-mono">{last ? sourceLabel(last.source) : NOT_SYNCED}</dd>
                </div>
              </dl>
            </div>
          </section>

          <p className="rounded-md border bg-muted/40 px-3 py-2 text-xs leading-5 text-muted-foreground">
            <span className="font-medium text-foreground">数据覆盖</span>
            {analysis.coverage.map((row) => (
              <span key={row.bar} className="ml-2">
                {BAR_LABELS[row.bar]}
                {row.available && row.available_from && row.available_to
                  ? ` ${formatBeijingTime(row.available_from, false)} 至 ${formatBeijingTime(
                      row.available_to,
                      false,
                    )}，共 ${row.candle_count} 根`
                  : ` ${row.unavailable_reason ?? NOT_SYNCED}`}
                ；
              </span>
            ))}
          </p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1.4fr]">
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">近 20 根阻力</p>
                <p className="mt-1 font-mono text-xl font-semibold">
                  {numberLabel(levels?.high20)}
                </p>
                <p className="text-xs text-muted-foreground">
                  距现价 {percentLabel(levels?.high_distance_pct ?? null)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">近 20 根支撑</p>
                <p className="mt-1 font-mono text-xl font-semibold">
                  {numberLabel(levels?.low20)}
                </p>
                <p className="text-xs text-muted-foreground">
                  距现价 {percentLabel(levels?.low_distance_pct ?? null)}
                </p>
              </CardContent>
            </Card>
            <Card className="sm:col-span-2 xl:col-span-1">
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">关联资产 · 60 日相关系数</p>
                {correlations.length === 0 ? (
                  <p className="mt-1 text-sm text-muted-foreground">尚未生成</p>
                ) : (
                  <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1">
                    {correlations.map((row) => (
                      <span key={row.inst_id} className="text-xs text-muted-foreground">
                        {row.inst_id}
                        <b
                          className={cn(
                            "ml-1.5 font-mono text-sm font-medium",
                            valueTone(row.coefficient),
                          )}
                        >
                          {row.coefficient == null ? "样本不足" : numberLabel(row.coefficient)}
                        </b>
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>K 线与均线</CardTitle>
                  <CardDescription>
                    {BAR_LABELS[bar]}开高低收与成交量；均线、缺口标记均来自后端。
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <i className="h-2 w-2 rounded-sm bg-emerald-600" aria-hidden="true" />
                    上涨
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i className="h-2 w-2 rounded-sm bg-rose-600" aria-hidden="true" />
                    下跌
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i className="h-0.5 w-4 bg-sky-500" aria-hidden="true" />
                    MA20
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i className="h-0.5 w-4 bg-amber-500" aria-hidden="true" />
                    MA60
                  </span>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {currentCoverage && !currentCoverage.available ? (
                <p className="mb-3 rounded-md border border-amber-600/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                  {BAR_LABELS[bar]}不可用：{currentCoverage.unavailable_reason ?? NOT_SYNCED}
                </p>
              ) : null}
              <CandlestickChart data={candles ?? { candles: [], overlays: [], gaps: [] }} />
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="rounded-full border px-2 py-0.5">周期 {BAR_LABELS[bar]}</span>
                <span className="rounded-full border px-2 py-0.5">
                  数据源 {candles ? sourceLabel(candles.data_source) : "未生成"}
                </span>
                <span className="rounded-full border px-2 py-0.5">
                  {candles && candles.candles.length > 0
                    ? `${candles.candles.length} 根 K 线`
                    : NOT_SYNCED}
                </span>
                <span className="rounded-full border px-2 py-0.5">
                  {candles && candles.gaps.length > 0
                    ? `${candles.gaps.length} 个缺口`
                    : "无缺口标记"}
                </span>
              </div>
            </CardContent>
          </Card>

          {indicators ? (
            <section className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="指标">
              <TrendCard indicators={indicators} />
              <MomentumCard indicators={indicators} />
              <VolatilityCard indicators={indicators} />
              <VolumeCard indicators={indicators} />
              <RelativeStrengthCard indicators={indicators} />
            </section>
          ) : null}

          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>读数</CardTitle>
                  <CardDescription>由后端按指标数值生成，不含买卖建议。</CardDescription>
                </div>
                <span className="text-xs text-muted-foreground">
                  {indicators ? `${indicators.readings.length} 条` : "未生成"}
                </span>
              </div>
            </CardHeader>
            <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
              <div className="space-y-3">
                {indicators && indicators.readings.length > 0 ? (
                  indicators.readings.map((sentence) => (
                    <p key={sentence} className="text-sm leading-7 text-foreground/85">
                      {sentence}
                    </p>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">未生成</p>
                )}
              </div>
              <dl>
                <Fact label="近 20 根最高" value={numberLabel(levels?.high20)} />
                <Fact label="近 20 根最低" value={numberLabel(levels?.low20)} />
                <Fact label="20 日均量" value={numberLabel(indicators?.volume.average20)} />
                <Fact
                  label="与基准相关"
                  value={numberLabel(
                    correlations.find((row) => row.role === "benchmark")?.coefficient,
                  )}
                />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>相关性</CardTitle>
              <CardDescription>
                60 日收益率相关系数；有效样本不足时写「样本不足」，不按 0 处理。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {correlations.length === 0 ? (
                <p className="text-sm text-muted-foreground">尚未生成相关性。</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-left">
                    <thead>
                      <tr className="border-b text-xs text-muted-foreground">
                        <th className="pb-2 pr-4 font-medium">标的</th>
                        <th className="pb-2 pr-4 font-medium">角色</th>
                        <th className="pb-2 pr-4 font-medium">相关系数</th>
                        <th className="pb-2 pr-4 font-medium">有效样本</th>
                        <th className="pb-2 font-medium">窗口</th>
                      </tr>
                    </thead>
                    <tbody>
                      {correlations.map((row) => (
                        <CorrelationRow key={`${row.role}-${row.inst_id}`} row={row} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>关联策略</CardTitle>
              <CardDescription>
                只显示过去 30 天内该标的的回测；点一行进入回测详情。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {linked.length === 0 ? (
                <p className="text-sm text-muted-foreground">近 30 天没有该标的的回测记录。</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[860px] text-left">
                    <thead>
                      <tr className="border-b text-xs text-muted-foreground">
                        <th className="pb-2 pr-4 font-medium">策略</th>
                        <th className="pb-2 pr-4 font-medium">回测区间</th>
                        <th className="pb-2 pr-4 text-right font-medium">收益</th>
                        <th className="pb-2 pr-4 text-right font-medium">最大回撤</th>
                        <th className="pb-2 pr-4 text-right font-medium">交易数</th>
                        <th className="pb-2 pr-4 font-medium">回测日期</th>
                        <th className="pb-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {linked.map((row) => (
                        <LinkedStrategyRow key={row.run_id} row={row} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>数据覆盖</CardTitle>
              <CardDescription>决定哪些周期可用；未同步的周期不显示 0。</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-left">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="pb-2 pr-4 font-medium">周期</th>
                      <th className="pb-2 pr-4 font-medium">来源</th>
                      <th className="pb-2 pr-4 font-medium">起止时间</th>
                      <th className="pb-2 pr-4 text-right font-medium">K 线数量</th>
                      <th className="pb-2 pr-4 text-right font-medium">缺口数</th>
                      <th className="pb-2 pr-4 font-medium">最后同步</th>
                      <th className="pb-2 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.coverage.map((row) => (
                      <CoverageRow key={row.bar} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}
